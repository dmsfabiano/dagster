import {
  AssetCheck,
  AssetCheckCanExecuteIndividually,
  AssetCheckHandleInput,
} from '../graphql/types';

import {LaunchAssetExecutionAssetNodeFragment} from './types/LaunchAssetExecutionButton.types';

// Checks that REQUIRES_MATERIALIZATION cannot be omitted and need to be executed
// whenver the asset is executed. Checks with CAN_EXECUTE should be omitted if their
// jobNames array does not include the requested job.
//
export function inMaterializeFunctionOrInJob(
  check: Pick<AssetCheck, 'jobNames' | 'canExecuteIndividually'>,
  jobName?: string,
) {
  const inJob = !jobName || check.jobNames.includes(jobName);
  const inMaterialize =
    check.canExecuteIndividually === AssetCheckCanExecuteIndividually.REQUIRES_MATERIALIZATION;

  return inMaterialize || inJob;
}

export function getAssetCheckHandleInputs(
  assets: Pick<LaunchAssetExecutionAssetNodeFragment, 'assetKey' | 'assetChecksOrError'>[],
  jobName?: string,
): AssetCheckHandleInput[] {
  return assets.flatMap((a) =>
    a.assetChecksOrError.__typename === 'AssetChecks'
      ? a.assetChecksOrError.checks
          .filter((check) => inMaterializeFunctionOrInJob(check, jobName))
          .map((check) => ({
            name: check.name,
            assetKey: {path: a.assetKey.path},
          }))
      : [],
  );
}

// The `.map` calls below sanitize the __typename and other possible fields out of the
// assetSelection / assetCheckSelection because GraphQL is strict about extra values.

export function asAssetKeyInput(assetOrAssetKey: {assetKey: {path: string[]}} | {path: string[]}) {
  return 'path' in assetOrAssetKey
    ? {path: assetOrAssetKey.path}
    : {path: assetOrAssetKey.assetKey.path};
}

export function asAssetCheckHandleInput(check: {name: string; assetKey: {path: string[]}}) {
  return {name: check.name, assetKey: {path: check.assetKey.path}};
}
