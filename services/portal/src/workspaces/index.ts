import type { ComponentType } from "react";
import type { WorkspaceProps } from "../pages/DemoPage";
import D2Chat from "./D2Chat";
import D5Legal from "./D5Legal";
import D6Assistant from "./D6Assistant";
import D7Complaints from "./D7Complaints";

// Live workspace per demo; demos without one show the placeholder and the deck's decision card.
export const WORKSPACES: Record<string, ComponentType<WorkspaceProps>> = {
  d2: D2Chat,
  d5: D5Legal,
  d6: D6Assistant,
  d7: D7Complaints,
};
