import type { ComponentType } from "react";
import type { WorkspaceProps } from "../pages/DemoPage";
import D1DocVerify from "./D1DocVerify";
import D2Chat from "./D2Chat";
import D3Campaigns from "./D3Campaigns";
import D4Agent from "./D4Agent";
import D5Legal from "./D5Legal";
import D6Assistant from "./D6Assistant";
import D7Complaints from "./D7Complaints";

// Live workspace per demo (all seven).
export const WORKSPACES: Record<string, ComponentType<WorkspaceProps>> = {
  d1: D1DocVerify,
  d2: D2Chat,
  d3: D3Campaigns,
  d4: D4Agent,
  d5: D5Legal,
  d6: D6Assistant,
  d7: D7Complaints,
};
