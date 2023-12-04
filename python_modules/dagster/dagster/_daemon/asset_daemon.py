import logging
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import ExitStack
from types import TracebackType
from typing import Dict, Optional, Sequence, Tuple, Type, cast

import pendulum

import dagster._check as check
from dagster._core.definitions.asset_daemon_context import AssetDaemonContext
from dagster._core.definitions.asset_daemon_cursor import AssetDaemonCursor
from dagster._core.definitions.events import AssetKey
from dagster._core.definitions.external_asset_graph import ExternalAssetGraph
from dagster._core.definitions.repository_definition.valid_definitions import (
    SINGLETON_REPOSITORY_NAME,
)
from dagster._core.definitions.run_request import (
    InstigatorType,
    RunRequest,
)
from dagster._core.definitions.selector import JobSubsetSelector
from dagster._core.errors import (
    DagsterCodeLocationLoadError,
    DagsterUserCodeUnreachableError,
)
from dagster._core.host_representation.external import (
    ExternalExecutionPlan,
    ExternalJob,
)
from dagster._core.host_representation.origin import (
    ExternalInstigatorOrigin,
)
from dagster._core.instance import DagsterInstance
from dagster._core.scheduler.instigation import (
    AutoMaterializeInstigatorData,
    InstigatorState,
    InstigatorStatus,
    InstigatorTick,
    TickData,
    TickStatus,
)
from dagster._core.storage.dagster_run import DagsterRun, DagsterRunStatus
from dagster._core.storage.tags import (
    ASSET_EVALUATION_ID_TAG,
    AUTO_MATERIALIZE_TAG,
    AUTO_OBSERVE_TAG,
)
from dagster._core.utils import InheritContextThreadPoolExecutor, make_new_run_id
from dagster._core.workspace.context import IWorkspaceProcessContext
from dagster._core.workspace.workspace import IWorkspace
from dagster._daemon.daemon import DaemonIterator, DagsterDaemon
from dagster._utils import (
    SingleInstigatorDebugCrashFlags,
    check_for_debug_crash,
    hash_collection,
)
from dagster._utils.error import serializable_error_info_from_exc_info

_PRE_EVALUATION_GROUP_CURSOR_KEY = "ASSET_DAEMON_CURSOR"
ASSET_DAEMON_PAUSED_KEY = "ASSET_DAEMON_PAUSED"

EVALUATIONS_TTL_DAYS = 30

# When retrying a tick, how long to wait before ignoring it and moving on to the next one
# (To account for the rare case where the daemon is down for a long time, starts back up, and
# there's an old in-progress tick left to finish that may no longer be correct to finish)
MAX_TIME_TO_RESUME_TICK_SECONDS = 60 * 60 * 24

_PRE_EVALUATION_GROUP_ORIGIN_ID = "asset_daemon_origin"
_PRE_EVALUATION_GROUP_SELECTOR_ID = "asset_daemon_selector"
_PRE_EVALUATION_GROUP_INSTIGATOR_NAME = "asset_daemon"

MIN_INTERVAL_LOOP_TIME = 5

DEFAULT_INSTIGATOR_NAME = "__default__"


def get_auto_materialize_paused(instance: DagsterInstance) -> bool:
    return (
        instance.daemon_cursor_storage.get_cursor_values({ASSET_DAEMON_PAUSED_KEY}).get(
            ASSET_DAEMON_PAUSED_KEY
        )
        != "false"
    )


def set_auto_materialize_paused(instance: DagsterInstance, paused: bool):
    instance.daemon_cursor_storage.set_cursor_values(
        {ASSET_DAEMON_PAUSED_KEY: "true" if paused else "false"}
    )


def _get_pre_evaluation_group_raw_cursor(instance: DagsterInstance) -> Optional[str]:
    return instance.daemon_cursor_storage.get_cursor_values({_PRE_EVALUATION_GROUP_CURSOR_KEY}).get(
        _PRE_EVALUATION_GROUP_CURSOR_KEY
    )


def get_instigator_origin_for_asset_key(
    asset_key: AssetKey, asset_graph: ExternalAssetGraph
) -> Optional[ExternalInstigatorOrigin]:
    # This will change to include user-defined evaluation groups once those can be set in code.
    # For now, every repository with at least one asset with an AMP policy also contains a
    # single instigator called DEFAULT_INSTIGATOR_NAME - every asset with an AMP policy in that
    # repository is considered part of it
    if not asset_graph.auto_materialize_policies_by_key.get(asset_key):
        return None

    repo_handle = asset_graph.get_repository_handle(asset_key)
    return ExternalInstigatorOrigin(
        external_repository_origin=repo_handle.get_external_origin(),
        instigator_name=DEFAULT_INSTIGATOR_NAME,
    )


def get_current_evaluation_id(
    instance: DagsterInstance, group_origin: Optional[ExternalInstigatorOrigin]
) -> Optional[int]:
    if not group_origin:
        raw_cursor = _get_pre_evaluation_group_raw_cursor(instance)
    else:
        instigator_state = check.not_none(instance.schedule_storage).get_instigator_state(
            group_origin.get_id(), group_origin.get_selector().get_id()
        )
        raw_cursor = (
            cast(AutoMaterializeInstigatorData, instigator_state.instigator_data).serialized_cursor
            if instigator_state
            else None
        )

    return AssetDaemonCursor.get_evaluation_id_from_serialized(raw_cursor) if raw_cursor else None


class AutoMaterializeLaunchContext:
    def __init__(
        self,
        tick: InstigatorTick,
        group_origin: Optional[ExternalInstigatorOrigin],
        instance: DagsterInstance,
        logger: logging.Logger,
        tick_retention_settings,
    ):
        self._tick = tick
        self._logger = logger
        self._instance = instance
        self._group_origin = group_origin

        self._purge_settings = defaultdict(set)
        for status, day_offset in tick_retention_settings.items():
            self._purge_settings[day_offset].add(status)

    @property
    def status(self) -> TickStatus:
        return self._tick.status

    @property
    def tick(self) -> InstigatorTick:
        return self._tick

    @property
    def logger(self) -> logging.Logger:
        return self._logger

    def add_run_info(self, run_id=None):
        self._tick = self._tick.with_run_info(run_id)

    def set_run_requests(
        self,
        run_requests: Sequence[RunRequest],
        reserved_run_ids: Optional[Sequence[str]],
    ):
        self._tick = self._tick.with_run_requests(run_requests, reserved_run_ids=reserved_run_ids)
        return self._tick

    def update_state(self, status: TickStatus, **kwargs: object):
        self._tick = self._tick.with_status(status=status, **kwargs)

    def __enter__(self):
        return self

    def __exit__(
        self,
        exception_type: Type[BaseException],
        exception_value: Exception,
        traceback: TracebackType,
    ) -> None:
        if exception_value and isinstance(exception_value, KeyboardInterrupt):
            return

        # Log the error if the failure wasn't an interrupt or the daemon generator stopping
        if exception_value and not isinstance(exception_value, GeneratorExit):
            if isinstance(
                exception_value, (DagsterUserCodeUnreachableError, DagsterCodeLocationLoadError)
            ):
                try:
                    raise Exception(
                        "Unable to reach the code server. Auto-materialization will resume once the code server is available."
                    ) from exception_value
                except:
                    error_data = serializable_error_info_from_exc_info(sys.exc_info())
                    self._logger.exception("Auto-materialize daemon caught an error")
                    self.update_state(
                        TickStatus.FAILURE,
                        error=error_data,
                        # don't increment the failure count - retry until the server is available again
                        failure_count=self._tick.failure_count,
                    )
            else:
                error_data = serializable_error_info_from_exc_info(sys.exc_info())
                self._logger.exception("Auto-materialize daemon caught an error")
                self.update_state(
                    TickStatus.FAILURE, error=error_data, failure_count=self._tick.failure_count + 1
                )

        check.invariant(
            self._tick.status != TickStatus.STARTED,
            "Tick must be in a terminal state when the AutoMaterializeLaunchContext is closed",
        )

        # write the new tick status to the database

        self.write()

        for day_offset, statuses in self._purge_settings.items():
            if day_offset <= 0:
                continue
            self._instance.purge_ticks(
                (
                    self._group_origin.get_id()
                    if self._group_origin
                    else _PRE_EVALUATION_GROUP_ORIGIN_ID
                ),
                (
                    self._group_origin.get_selector().get_id()
                    if self._group_origin
                    else _PRE_EVALUATION_GROUP_SELECTOR_ID
                ),
                before=pendulum.now("UTC").subtract(days=day_offset).timestamp(),
                tick_statuses=list(statuses),
            )

    def write(self) -> None:
        self._instance.update_tick(self._tick)


class AssetDaemon(DagsterDaemon):
    def __init__(self, interval_seconds: int):
        self._interval_seconds = interval_seconds

        self._initialized_evaluation_id = None

        self._evaluation_id_lock = threading.Lock()
        self._next_evaluation_id = None

        super().__init__()

    @classmethod
    def daemon_type(cls) -> str:
        return "ASSET"

    def _initialize_evaluation_id(
        self,
        instance: DagsterInstance,
        asset_graph: ExternalAssetGraph,
    ):
        # Find the largest stored evaluation ID across all cursors
        with self._evaluation_id_lock:
            all_auto_materialize_states = check.not_none(
                instance.schedule_storage
            ).all_instigator_state(instigator_type=InstigatorType.AUTO_MATERIALIZE)
            self._next_evaluation_id = 0
            for auto_materialize_state in all_auto_materialize_states:
                raw_cursor = cast(
                    AutoMaterializeInstigatorData, auto_materialize_state.instigator_data
                ).serialized_cursor
                if raw_cursor:
                    stored_evaluation_id = AssetDaemonCursor.from_serialized(
                        raw_cursor,
                        asset_graph,
                    ).evaluation_id
                    self._next_evaluation_id = max(self._next_evaluation_id, stored_evaluation_id)

            raw_cursor = _get_pre_evaluation_group_raw_cursor(instance)
            if raw_cursor:
                stored_cursor = AssetDaemonCursor.from_serialized(raw_cursor, asset_graph)
                self._next_evaluation_id = max(
                    self._next_evaluation_id, stored_cursor.evaluation_id
                )

    def _get_next_evaluation_id(self):
        with self._evaluation_id_lock:
            check.invariant(self._initialized_evaluation_id)
            self._next_evaluation_id = self._next_evaluation_id + 1
            return self._next_evaluation_id

    def core_loop(
        self,
        workspace_process_context: IWorkspaceProcessContext,
        shutdown_event: threading.Event,
    ) -> DaemonIterator:
        yield from self.execute_amp_iteration_loop(
            workspace_process_context,
            shutdown_event=shutdown_event,
            debug_crash_flags={},
        )

    def execute_amp_iteration_loop(
        self,
        workspace_process_context: IWorkspaceProcessContext,
        shutdown_event: threading.Event,
        debug_crash_flags: SingleInstigatorDebugCrashFlags,
    ) -> DaemonIterator:
        instance: DagsterInstance = workspace_process_context.instance

        schedule_storage = check.not_none(
            instance.schedule_storage,
            "Auto materialization requires schedule storage to be configured",
        )

        if not schedule_storage.supports_auto_materialize_asset_evaluations:
            self._logger.warning(
                "Auto materialize evaluations are not getting logged. Run `dagster instance"
                " migrate` to enable."
            )

        amp_tick_futures: Dict[Optional[str], Future] = {}
        last_submit_times = {}
        threadpool_executor = None
        with ExitStack() as stack:
            settings = instance.get_settings("auto_materialize")
            if settings.get("use_threads"):
                threadpool_executor = stack.enter_context(
                    InheritContextThreadPoolExecutor(
                        max_workers=settings.get("num_workers"),
                        thread_name_prefix="asset_daemon_worker",
                    )
                )

            while True:
                start_time = pendulum.now("UTC").timestamp()
                yield from self._run_iteration_impl(
                    workspace_process_context,
                    threadpool_executor=threadpool_executor,
                    amp_tick_futures=amp_tick_futures,
                    last_submit_times=last_submit_times,
                    debug_crash_flags={},
                )
                yield None
                end_time = pendulum.now("UTC").timestamp()
                loop_duration = end_time - start_time
                sleep_time = max(0, MIN_INTERVAL_LOOP_TIME - loop_duration)
                shutdown_event.wait(sleep_time)
                yield None

    def _run_iteration_impl(
        self,
        workspace_process_context: IWorkspaceProcessContext,
        threadpool_executor: Optional[ThreadPoolExecutor],
        amp_tick_futures: Dict[Optional[str], Future],
        last_submit_times: Dict[Optional[str], float],
        debug_crash_flags: SingleInstigatorDebugCrashFlags,  # TODO No longer single instigator
    ):
        workspace = workspace_process_context.create_request_context()
        asset_graph = ExternalAssetGraph.from_workspace(workspace)

        instance: DagsterInstance = workspace_process_context.instance
        settings = instance.get_settings("auto_materialize")

        now = time.time()

        if get_auto_materialize_paused(instance):
            yield
            return

        if not self._initialized_evaluation_id:
            self._initialize_evaluation_id(instance, asset_graph)
            self._initialized_evaluation_id = True

        group_origins: Sequence[Optional[ExternalInstigatorOrigin]]

        if settings.get("use_asset_policy_sensors"):
            # TODO This will include user-defined evaluation groups once there is a
            # user-facing way to set them. For now, every repository with at least one
            # asset with an AMP policy or auto-observe interval gets a group for that repository

            origins_dict = {}

            for asset_key, policy in asset_graph.auto_materialize_policies_by_key.items():
                if not policy:
                    continue
                origin = get_instigator_origin_for_asset_key(asset_key, asset_graph)
                if origin:
                    origins_dict[origin.get_id()] = origin

            for asset_key in asset_graph.source_asset_keys:
                if asset_graph.get_auto_observe_interval_minutes(asset_key) is not None:
                    continue

                origin = get_instigator_origin_for_asset_key(asset_key, asset_graph)
                if origin:
                    origins_dict[origin.get_id()] = origin

            all_auto_materialize_states = {
                sensor_state.selector_id: sensor_state
                for sensor_state in instance.all_instigator_state(
                    instigator_type=InstigatorType.AUTO_MATERIALIZE
                )
            }
            group_origins = list(origins_dict.values())

            # TODO Adapt stored legacy cursor into per-evaluation-group cursors the first time AMP is run
            # using evaluation groups
        else:
            group_origins = [None]  # None = all assets
            all_auto_materialize_states = {}

        for group_origin in group_origins:
            group_selector_id = group_origin.get_selector().get_id() if group_origin else None

            auto_materialize_state = all_auto_materialize_states.get(group_selector_id)

            # only one tick per evaluation group can be in flight
            if threadpool_executor:
                if (
                    group_selector_id in amp_tick_futures
                    and not amp_tick_futures[group_selector_id].done()
                ):
                    continue

                if (
                    group_selector_id in last_submit_times
                    and now < last_submit_times[group_selector_id] + self._interval_seconds
                ):
                    continue

                last_submit_times[group_selector_id] = now

                future = threadpool_executor.submit(
                    self._process_auto_materialize_tick,
                    workspace_process_context,
                    group_origin,
                    auto_materialize_state,
                    debug_crash_flags,
                )
                amp_tick_futures[group_selector_id] = future
                yield
            else:
                if (
                    group_selector_id in last_submit_times
                    and now < last_submit_times[group_selector_id] + self._interval_seconds
                ):
                    continue

                last_submit_times[group_selector_id] = now

                yield from self._process_auto_materialize_tick_generator(
                    workspace_process_context,
                    group_origin,
                    auto_materialize_state,
                    debug_crash_flags,
                )

    def _get_display_group_name(self, group_origin: Optional[ExternalInstigatorOrigin]) -> str:
        if not group_origin:
            return "global evaluation group"
        else:
            repo_name = (
                group_origin.external_repository_origin.get_label()
                if group_origin.external_repository_origin.repository_name
                != SINGLETON_REPOSITORY_NAME
                else group_origin.external_repository_origin.code_location_origin.location_name
            )

            if group_origin.instigator_name == DEFAULT_INSTIGATOR_NAME:
                return f"default asset policy sensor in {repo_name}"
            else:
                return f"asset policy sensor {group_origin.instigator_name} in {repo_name}"

    def _process_auto_materialize_tick(
        self,
        workspace_process_context: IWorkspaceProcessContext,
        group_origin: Optional[ExternalInstigatorOrigin],
        auto_materialize_instigator_state: Optional[InstigatorState],
        debug_crash_flags: SingleInstigatorDebugCrashFlags,  # TODO No longer single instigator
    ):
        return list(
            self._process_auto_materialize_tick_generator(
                workspace_process_context,
                group_origin,
                auto_materialize_instigator_state,
                debug_crash_flags,
            )
        )

    def _process_auto_materialize_tick_generator(
        self,
        workspace_process_context: IWorkspaceProcessContext,
        group_origin: Optional[ExternalInstigatorOrigin],
        auto_materialize_instigator_state: Optional[InstigatorState],
        debug_crash_flags: SingleInstigatorDebugCrashFlags,  # TODO No longer single instigator
    ):
        evaluation_time = pendulum.now("UTC")

        workspace = workspace_process_context.create_request_context()
        asset_graph = ExternalAssetGraph.from_workspace(workspace)

        instance: DagsterInstance = workspace_process_context.instance
        schedule_storage = check.not_none(instance.schedule_storage)

        print_group_name = self._get_display_group_name(group_origin)

        target_asset_keys = {
            target_key
            for target_key in asset_graph.materializable_asset_keys
            if asset_graph.get_auto_materialize_policy(target_key) is not None
            and (
                not group_origin
                or get_instigator_origin_for_asset_key(target_key, asset_graph) == group_origin
            )
        }

        num_target_assets = len(target_asset_keys)

        auto_observe_assets = [
            key
            for key in asset_graph.source_asset_keys
            if asset_graph.get_auto_observe_interval_minutes(key) is not None
            and (
                not group_origin
                or get_instigator_origin_for_asset_key(key, asset_graph) == group_origin
            )
        ]

        num_auto_observe_assets = len(auto_observe_assets)
        has_auto_observe_assets = any(auto_observe_assets)

        if not target_asset_keys and not has_auto_observe_assets:
            self._logger.debug(
                "No assets that require auto-materialize checks for {print_group_name}"
            )
            yield
            return

        self._logger.info(
            f"Checking {num_target_assets} asset{'' if num_target_assets == 1 else 's'} and"
            f" {num_auto_observe_assets} observable source"
            f" asset{'' if num_auto_observe_assets == 1 else 's'} for {print_group_name}"
        )

        if group_origin:
            if not auto_materialize_instigator_state:
                auto_materialize_instigator_state = InstigatorState(
                    group_origin,
                    InstigatorType.AUTO_MATERIALIZE,
                    InstigatorStatus.AUTOMATICALLY_RUNNING,
                    AutoMaterializeInstigatorData(
                        serialized_cursor=AssetDaemonCursor.empty().serialize(),
                    ),
                )
                instance.add_instigator_state(auto_materialize_instigator_state)

            raw_cursor = cast(
                AutoMaterializeInstigatorData, auto_materialize_instigator_state.instigator_data
            ).serialized_cursor
            stored_cursor = AssetDaemonCursor.from_serialized(
                check.not_none(raw_cursor), asset_graph
            )
            instigator_origin_id = group_origin.get_id()
            instigator_selector_id = group_origin.get_selector().get_id()
            instigator_name = group_origin.instigator_name
        else:
            raw_cursor = _get_pre_evaluation_group_raw_cursor(instance)
            stored_cursor = (
                AssetDaemonCursor.from_serialized(raw_cursor, asset_graph)
                if raw_cursor
                else AssetDaemonCursor.empty()
            )
            instigator_origin_id = _PRE_EVALUATION_GROUP_ORIGIN_ID
            instigator_selector_id = _PRE_EVALUATION_GROUP_SELECTOR_ID
            instigator_name = _PRE_EVALUATION_GROUP_INSTIGATOR_NAME

        tick_retention_settings = instance.get_tick_retention_settings(
            InstigatorType.AUTO_MATERIALIZE
        )

        ticks = instance.get_ticks(instigator_origin_id, instigator_selector_id, limit=1)
        latest_tick = ticks[0] if ticks else None

        max_retries = instance.auto_materialize_max_tick_retries

        # Determine if the most recent tick requires retrying
        retry_tick: Optional[InstigatorTick] = None

        if latest_tick:
            # If the previous tick matches the stored cursor's evaluation ID, check if it failed
            # or crashed partway through execution and needs to be resumed
            # Don't resume very old ticks though in case the daemon crashed for a long time and
            # then restarted
            if (
                pendulum.now("UTC").timestamp() - latest_tick.timestamp
                <= MAX_TIME_TO_RESUME_TICK_SECONDS
                and latest_tick.tick_data.auto_materialize_evaluation_id
                == stored_cursor.evaluation_id
            ):
                if latest_tick.status == TickStatus.STARTED:
                    self._logger.warn(
                        f"Tick for evaluation {stored_cursor.evaluation_id} for {print_group_name} was interrupted part-way through, resuming"
                    )
                    retry_tick = latest_tick
                elif (
                    latest_tick.status == TickStatus.FAILURE
                    and latest_tick.tick_data.failure_count <= max_retries
                ):
                    self._logger.info(
                        f"Retrying failed tick for evaluation {stored_cursor.evaluation_id} for {print_group_name}"
                    )
                    retry_tick = instance.create_tick(
                        latest_tick.tick_data.with_status(
                            TickStatus.STARTED,
                            error=None,
                            timestamp=evaluation_time.timestamp(),
                            end_timestamp=None,
                        ),
                    )
            else:
                # (The evaluation IDs not matching indicates that the tick failed or crashed before
                # the cursor could be written, so no runs have been launched and it's safe to
                # re-evaluate things from scratch in a new tick without retrying anything)
                if latest_tick.status == TickStatus.STARTED:
                    # Old tick that won't be resumed - move it into a SKIPPED state so it isn't
                    # left dangling in STARTED
                    self._logger.warn(
                        f"Moving dangling STARTED tick from evaluation {latest_tick.tick_data.auto_materialize_evaluation_id} for {print_group_name} into SKIPPED"
                    )
                    latest_tick = latest_tick.with_status(status=TickStatus.SKIPPED)
                    instance.update_tick(latest_tick)

        if retry_tick:
            tick = retry_tick
        else:
            # Evaluation ID will always be monotonically increasing, but will not always
            # be auto-incrementing by 1 once there are multiple AMP evaluations happening in
            # parallel
            next_evaluation_id = self._get_next_evaluation_id()
            tick = instance.create_tick(
                TickData(
                    instigator_origin_id=instigator_origin_id,
                    instigator_name=instigator_name,
                    instigator_type=InstigatorType.AUTO_MATERIALIZE,
                    status=TickStatus.STARTED,
                    timestamp=evaluation_time.timestamp(),
                    selector_id=instigator_selector_id,
                    auto_materialize_evaluation_id=next_evaluation_id,
                )
            )

        evaluation_id = check.not_none(tick.tick_data.auto_materialize_evaluation_id)

        with AutoMaterializeLaunchContext(
            tick,
            group_origin,
            instance,
            self._logger,
            tick_retention_settings,
        ) as tick_context:
            if retry_tick:
                # Unfinished or retried tick already generated evaluations and run requests and cursor, now
                # need to finish it
                run_requests = tick.tick_data.run_requests or []
                reserved_run_ids = tick.tick_data.reserved_run_ids or []

                if schedule_storage.supports_auto_materialize_asset_evaluations:
                    evaluation_records = (
                        schedule_storage.get_auto_materialize_evaluations_for_evaluation_id(
                            evaluation_id
                        )
                    )
                    evaluations_by_asset_key = {
                        evaluation_record.asset_key: evaluation_record.evaluation
                        for evaluation_record in evaluation_records
                    }
                else:
                    evaluations_by_asset_key = {}
            else:
                run_requests, new_cursor, evaluations = AssetDaemonContext(
                    evaluation_id=evaluation_id,
                    asset_graph=asset_graph,
                    target_asset_keys=target_asset_keys,
                    instance=instance,
                    cursor=stored_cursor,
                    materialize_run_tags={
                        **instance.auto_materialize_run_tags,
                    },
                    observe_run_tags={AUTO_OBSERVE_TAG: "true"},
                    auto_observe=True,
                    respect_materialization_data_versions=instance.auto_materialize_respect_materialization_data_versions,
                    logger=self._logger,
                ).evaluate()

                check.invariant(new_cursor.evaluation_id == evaluation_id)

                check_for_debug_crash(debug_crash_flags, "EVALUATIONS_FINISHED")

                evaluations_by_asset_key = {
                    evaluation.asset_key: evaluation for evaluation in evaluations
                }

                # Write the asset evaluations without run IDs first
                if schedule_storage.supports_auto_materialize_asset_evaluations:
                    schedule_storage.add_auto_materialize_asset_evaluations(
                        evaluation_id, list(evaluations_by_asset_key.values())
                    )
                    check_for_debug_crash(debug_crash_flags, "ASSET_EVALUATIONS_ADDED")

                reserved_run_ids = [make_new_run_id() for _ in range(len(run_requests))]

                # Write out the in-progress tick data, which ensures that if the tick crashes or raises an exception, it will retry
                tick = tick_context.set_run_requests(
                    run_requests=run_requests,
                    reserved_run_ids=reserved_run_ids,
                )
                tick_context.write()
                check_for_debug_crash(debug_crash_flags, "RUN_REQUESTS_CREATED")

                if group_origin:
                    instance.update_instigator_state(
                        check.not_none(auto_materialize_instigator_state).with_data(
                            AutoMaterializeInstigatorData(serialized_cursor=new_cursor.serialize())
                        )
                    )
                else:
                    # Write out the persistent cursor, which ensures that future ticks will move on once
                    # they determine that nothing needs to be retried
                    instance.daemon_cursor_storage.set_cursor_values(
                        {_PRE_EVALUATION_GROUP_CURSOR_KEY: new_cursor.serialize()}
                    )

                check_for_debug_crash(debug_crash_flags, "CURSOR_UPDATED")

            self._logger.info(
                "Tick produced"
                f" {len(run_requests)} run{'s' if len(run_requests) != 1 else ''} and"
                f" {len(evaluations_by_asset_key)} asset"
                f" evaluation{'s' if len(evaluations_by_asset_key) != 1 else ''} for evaluation ID"
                f" {evaluation_id} for {print_group_name}"
            )

            pipeline_and_execution_plan_cache: Dict[
                int, Tuple[ExternalJob, ExternalExecutionPlan]
            ] = {}

            check.invariant(len(run_requests) == len(reserved_run_ids))

            updated_evaluation_asset_keys = set()

            for i in range(len(run_requests)):
                reserved_run_id = reserved_run_ids[i]
                run_request = run_requests[i]

                asset_keys = check.not_none(run_request.asset_selection)

                submitted_run = submit_asset_run(
                    reserved_run_id,
                    run_request._replace(
                        tags={
                            **run_request.tags,
                            AUTO_MATERIALIZE_TAG: "true",
                            ASSET_EVALUATION_ID_TAG: str(evaluation_id),
                        }
                    ),
                    instance,
                    workspace,
                    asset_graph,
                    pipeline_and_execution_plan_cache,
                    self._logger,
                    debug_crash_flags,
                    i,
                )

                tick_context.add_run_info(run_id=submitted_run.run_id)

                # write the submitted run ID to any evaluations
                for asset_key in asset_keys:
                    # asset keys for observation runs don't have evaluations
                    if asset_key in evaluations_by_asset_key:
                        evaluation = evaluations_by_asset_key[asset_key]
                        evaluations_by_asset_key[asset_key] = evaluation._replace(
                            run_ids=evaluation.run_ids | {submitted_run.run_id}
                        )
                        updated_evaluation_asset_keys.add(asset_key)

            evaluations_to_update = [
                evaluations_by_asset_key[asset_key] for asset_key in updated_evaluation_asset_keys
            ]
            if evaluations_to_update:
                schedule_storage.add_auto_materialize_asset_evaluations(
                    evaluation_id, evaluations_to_update
                )

            check_for_debug_crash(debug_crash_flags, "RUN_IDS_ADDED_TO_EVALUATIONS")

            tick_context.update_state(
                TickStatus.SUCCESS if len(run_requests) > 0 else TickStatus.SKIPPED,
            )

        if schedule_storage.supports_auto_materialize_asset_evaluations:
            schedule_storage.purge_asset_evaluations(
                before=pendulum.now("UTC").subtract(days=EVALUATIONS_TTL_DAYS).timestamp(),
            )

        self._logger.info("Finished auto-materialization tick")


def submit_asset_run(
    run_id: str,
    run_request: RunRequest,
    instance: DagsterInstance,
    workspace: IWorkspace,
    asset_graph: ExternalAssetGraph,
    pipeline_and_execution_plan_cache: Dict[int, Tuple[ExternalJob, ExternalExecutionPlan]],
    logger: logging.Logger,
    debug_crash_flags: SingleInstigatorDebugCrashFlags,
    run_request_index: int,
) -> DagsterRun:
    check.invariant(
        not run_request.run_config, "Asset materialization run requests have no custom run config"
    )
    asset_keys = check.not_none(run_request.asset_selection)

    check.invariant(len(asset_keys) > 0)

    # check if the run already exists

    run_to_submit = None

    existing_run = instance.get_run_by_id(run_id)
    if existing_run:
        if existing_run.status != DagsterRunStatus.NOT_STARTED:
            logger.warn(
                f"Run {run_id} already submitted on a previously interrupted tick, skipping"
            )

            check_for_debug_crash(debug_crash_flags, "RUN_SUBMITTED")
            check_for_debug_crash(debug_crash_flags, f"RUN_SUBMITTED_{run_request_index}")

            return existing_run
        else:
            logger.warn(
                f"Run {run_id} already created on a previously interrupted tick, submitting"
            )
            run_to_submit = existing_run

    if not run_to_submit:
        repo_handle = asset_graph.get_repository_handle(asset_keys[0])

        # Check that all asset keys are from the same repo
        for key in asset_keys[1:]:
            check.invariant(repo_handle == asset_graph.get_repository_handle(key))

        location_name = repo_handle.code_location_origin.location_name
        repository_name = repo_handle.repository_name
        code_location = workspace.get_code_location(location_name)
        job_name = check.not_none(
            asset_graph.get_implicit_job_name_for_assets(
                asset_keys, code_location.get_repository(repository_name)
            )
        )

        job_selector = JobSubsetSelector(
            location_name=location_name,
            repository_name=repository_name,
            job_name=job_name,
            op_selection=None,
            asset_selection=asset_keys,
        )

        selector_id = hash_collection(job_selector)

        if selector_id not in pipeline_and_execution_plan_cache:
            external_job = code_location.get_external_job(job_selector)

            external_execution_plan = code_location.get_external_execution_plan(
                external_job,
                run_config={},
                step_keys_to_execute=None,
                known_state=None,
                instance=instance,
            )
            pipeline_and_execution_plan_cache[selector_id] = (
                external_job,
                external_execution_plan,
            )

        check_for_debug_crash(debug_crash_flags, "EXECUTION_PLAN_CREATED")
        check_for_debug_crash(debug_crash_flags, f"EXECUTION_PLAN_CREATED_{run_request_index}")

        external_job, external_execution_plan = pipeline_and_execution_plan_cache[selector_id]

        execution_plan_snapshot = external_execution_plan.execution_plan_snapshot

        run_to_submit = instance.create_run(
            job_name=external_job.name,
            run_id=run_id,
            run_config=None,
            resolved_op_selection=None,
            step_keys_to_execute=None,
            status=DagsterRunStatus.NOT_STARTED,
            op_selection=None,
            root_run_id=None,
            parent_run_id=None,
            tags=run_request.tags,
            job_snapshot=external_job.job_snapshot,
            execution_plan_snapshot=execution_plan_snapshot,
            parent_job_snapshot=external_job.parent_job_snapshot,
            external_job_origin=external_job.get_external_origin(),
            job_code_origin=external_job.get_python_origin(),
            asset_selection=frozenset(asset_keys),
            asset_check_selection=None,
        )

    check_for_debug_crash(debug_crash_flags, "RUN_CREATED")
    check_for_debug_crash(debug_crash_flags, f"RUN_CREATED_{run_request_index}")

    instance.submit_run(run_to_submit.run_id, workspace)

    check_for_debug_crash(debug_crash_flags, "RUN_SUBMITTED")
    check_for_debug_crash(debug_crash_flags, f"RUN_SUBMITTED_{run_request_index}")

    asset_key_str = ", ".join([asset_key.to_user_string() for asset_key in asset_keys])

    logger.info(
        f"Submitted run {run_to_submit.run_id} for assets {asset_key_str} with tags"
        f" {run_request.tags}"
    )

    return run_to_submit
