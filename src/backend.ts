import { call } from "@decky/api";

export type ComponentKey = "proton" | "turnip";

export interface Release {
  tag: string;
  version: string;
  name: string;
  prerelease: boolean;
  published: string | null;
  page: string;
  asset: string;
  size: number;
}

export interface Installed {
  version: string;
  name: string;
  path: string;
}

export interface Progress {
  stage: "downloading" | "verifying" | "installing" | "done" | "cancelled" | "error";
  done: number;
  total: number;
}

export interface ComponentState {
  key: ComponentKey;
  label: string;
  repo: string;
  target: string;
  installed: Installed[];
  current: string | null;
  latest: Release | null;
  update_available: boolean;
  latest_installed: boolean;
  allow_prerelease: boolean;
  error: string | null;
  busy: boolean;
  progress: Progress | null;
}

export type State = Record<ComponentKey, ComponentState>;

export const getState = () => call<[], State>("get_state");
export const checkUpdates = () => call<[], State>("check_updates");
export const setAllowPrerelease = (key: ComponentKey, value: boolean) =>
  call<[ComponentKey, boolean], State>("set_allow_prerelease", key, value);
export const install = (key: ComponentKey) => call<[ComponentKey], State>("install", key);
export const removeOldVersions = (key: ComponentKey) =>
  call<[ComponentKey], State>("remove_old_versions", key);
export const cancelInstall = (key: ComponentKey) => call<[ComponentKey], State>("cancel_install", key);
