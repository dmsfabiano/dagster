import {LegacyColors} from '../components/LegacyColors';

import {ColorName} from './ColorName';
import {CoreColors, DataVizColors} from './Colors';

export const LegacyPalette = {
  [ColorName.BrowserColorScheme]: 'light',
  [ColorName.KeylineDefault]: LegacyColors.KeylineGray,
  [ColorName.LinkDefault]: LegacyColors.Link,
  [ColorName.LinkHover]: LegacyColors.Link,
  [ColorName.LinkDisabled]: LegacyColors.Link,
  [ColorName.TextDefault]: LegacyColors.Dark,
  [ColorName.TextLight]: LegacyColors.Gray700,
  [ColorName.TextLighter]: LegacyColors.Gray600,
  [ColorName.TextDisabled]: LegacyColors.Gray300,
  [ColorName.TextRed]: LegacyColors.Red700,
  [ColorName.TextYellow]: LegacyColors.Yellow700,
  [ColorName.TextGreen]: LegacyColors.Green700,
  [ColorName.TextBlue]: LegacyColors.Blue700,
  [ColorName.TextOlive]: LegacyColors.Olive700,
  [ColorName.TextCyan]: LegacyColors.Blue700, // No cyan in Legacy
  [ColorName.TextLime]: LegacyColors.HighlightGreen, // No lime in Legacy
  [ColorName.BackgroundDefault]: LegacyColors.White,
  [ColorName.BackgroundDefaultHover]: LegacyColors.Gray50,
  [ColorName.BackgroundLight]: LegacyColors.Gray50,
  [ColorName.BackgroundLightHover]: LegacyColors.Gray100,
  [ColorName.BackgroundLighter]: LegacyColors.Gray10,
  [ColorName.BackgroundLighterHover]: LegacyColors.Gray200,
  [ColorName.BackgroundDisabled]: LegacyColors.Gray200,
  [ColorName.BackgroundRed]: LegacyColors.Red50,
  [ColorName.BackgroundRedHover]: LegacyColors.Red50,
  [ColorName.BackgroundYellow]: LegacyColors.Yellow50,
  [ColorName.BackgroundYellowHover]: LegacyColors.Yellow50,
  [ColorName.BackgroundGreen]: LegacyColors.Green50,
  [ColorName.BackgroundGreenHover]: LegacyColors.Green50,
  [ColorName.BackgroundBlue]: LegacyColors.Blue50,
  [ColorName.BackgroundBlueHover]: LegacyColors.Blue50,
  [ColorName.BackgroundOlive]: LegacyColors.Olive50,
  [ColorName.BackgroundOliverHover]: LegacyColors.Olive50,
  [ColorName.BackgroundCyan]: LegacyColors.Blue50, // No cyan
  [ColorName.BackgroundCyanHover]: LegacyColors.Blue50, // No cyan
  [ColorName.BackgroundLime]: LegacyColors.Green50, // No lime
  [ColorName.BackgroundLimeHover]: LegacyColors.Green50, // No lime
  [ColorName.BackgroundGray]: LegacyColors.Gray50,
  [ColorName.BackgroundGrayHover]: LegacyColors.Gray50,
  [ColorName.BorderDefault]: LegacyColors.Gray300,
  [ColorName.BorderHover]: LegacyColors.Gray200,
  [ColorName.BorderDisabled]: LegacyColors.Gray100,
  [ColorName.FocusRing]: CoreColors.Cyan400,
  [ColorName.AccentPrimary]: LegacyColors.Gray900,
  [ColorName.AccentPrimaryHover]: LegacyColors.Gray800,
  [ColorName.AccentReversed]: LegacyColors.White,
  [ColorName.AccentReversedHover]: LegacyColors.White,
  [ColorName.AccentRed]: LegacyColors.Red500,
  [ColorName.AccentRedHover]: LegacyColors.Red500,
  [ColorName.AccentYellow]: LegacyColors.Yellow500,
  [ColorName.AccentYellowHover]: LegacyColors.Yellow500,
  [ColorName.AccentGreen]: LegacyColors.Green500,
  [ColorName.AccentGreenHover]: LegacyColors.Green500,
  [ColorName.AccentBlue]: LegacyColors.Blue500,
  [ColorName.AccentBlueHover]: LegacyColors.Blue500,
  [ColorName.AccentCyan]: LegacyColors.Blue200, // No cyan
  [ColorName.AccentCyanHover]: LegacyColors.Blue200, // No cyan
  [ColorName.AccentLime]: LegacyColors.HighlightGreen, // No lime
  [ColorName.AccentLimeHover]: LegacyColors.HighlightGreen, // No lime
  [ColorName.AccentGray]: LegacyColors.Gray500,
  [ColorName.AccentGrayHover]: LegacyColors.Gray400,
  [ColorName.AccentLavender]: LegacyColors.Blue200,
  [ColorName.AccentLavenderHover]: LegacyColors.Blue100,
  [ColorName.AccentOlive]: LegacyColors.Olive500,
  [ColorName.AccentOliveHover]: LegacyColors.Olive500,
  [ColorName.AccentWhite]: LegacyColors.White,
  [ColorName.DialogBackground]: LegacyColors.WashGray,
  [ColorName.TooltipBackground]: LegacyColors.Dark,
  [ColorName.TooltipText]: LegacyColors.White,
  [ColorName.PopoverBackground]: LegacyColors.White,
  [ColorName.PopoverBackgroundHover]: LegacyColors.Gray100,

  // HEADER
  [ColorName.NavBackground]: LegacyColors.Dark,
  [ColorName.NavText]: LegacyColors.Gray500,
  [ColorName.NavTextHover]: LegacyColors.Gray300,
  [ColorName.NavTextSelected]: LegacyColors.Gray100,
  [ColorName.NavButton]: LegacyColors.Gray900,
  [ColorName.NavButtonHover]: LegacyColors.Gray800,

  // Lineage Graph
  [ColorName.LineageDots]: LegacyColors.Gray100,
  [ColorName.LineageEdge]: LegacyColors.Gray200,
  [ColorName.LineageEdgeHighlighted]: LegacyColors.Blue500,
  [ColorName.LineageGroupNodeBackground]: LegacyColors.Gray100,
  [ColorName.LineageGroupNodeBackgroundHover]: LegacyColors.KeylineGray,
  [ColorName.LineageGroupNodeBorder]: LegacyColors.Gray200,
  [ColorName.LineageGroupNodeBorderHover]: LegacyColors.Gray200,
  [ColorName.LineageGroupBackground]: LegacyColors.Gray10,
  [ColorName.LineageNodeBackground]: LegacyColors.Blue50,
  [ColorName.LineageNodeBackgroundHover]: LegacyColors.Blue50,
  [ColorName.LineageNodeBorder]: LegacyColors.Blue200,
  [ColorName.LineageNodeBorderHover]: LegacyColors.Blue500,
  [ColorName.LineageNodeBorderSelected]: LegacyColors.Blue500,

  // Dataviz
  [ColorName.DataVizBlue]: DataVizColors.Blue200,
  [ColorName.DataVizBlueAlt]: DataVizColors.Blue300,
  [ColorName.DataVizBlurple]: DataVizColors.Blurple200,
  [ColorName.DataVizBlurpleAlt]: DataVizColors.Blurple300,
  [ColorName.DataVizBrown]: DataVizColors.Brown200,
  [ColorName.DataVizBrownAlt]: DataVizColors.Brown300,
  [ColorName.DataVizCyan]: DataVizColors.Cyan200,
  [ColorName.DataVizCyanAlt]: DataVizColors.Cyan300,
  [ColorName.DataVizGray]: DataVizColors.Gray200,
  [ColorName.DataVizGrayAlt]: DataVizColors.Gray300,
  [ColorName.DataVizGreen]: DataVizColors.Green200,
  [ColorName.DataVizGreenAlt]: DataVizColors.Green300,
  [ColorName.DataVizLime]: DataVizColors.Lime200,
  [ColorName.DataVizLimeAlt]: DataVizColors.Lime300,
  [ColorName.DataVizOrange]: DataVizColors.Orange200,
  [ColorName.DataVizOrangeAlt]: DataVizColors.Orange300,
  [ColorName.DataVizPink]: DataVizColors.Pink200,
  [ColorName.DataVizPinkAlt]: DataVizColors.Pink300,
  [ColorName.DataVizRed]: DataVizColors.Red200,
  [ColorName.DataVizRedAlt]: DataVizColors.Red300,
  [ColorName.DataVizTeal]: DataVizColors.Teal200,
  [ColorName.DataVizTealAlt]: DataVizColors.Teal300,
  [ColorName.DataVizViolet]: DataVizColors.Violet200,
  [ColorName.DataVizVioletAlt]: DataVizColors.Violet300,
  [ColorName.DataVizYellow]: DataVizColors.Yellow200,
  [ColorName.DataVizYellowAlt]: DataVizColors.Yellow300,
};
