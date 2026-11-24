import { addEventListener, definePlugin, removeEventListener, toaster } from "@decky/api";
import {
  ButtonItem,
  ConfirmModal,
  Field,
  PanelSection,
  PanelSectionRow,
  ProgressBar,
  ToggleField,
  showModal,
  staticClasses,
} from "@decky/ui";
import { useCallback, useEffect, useState } from "react";
import {
  ComponentKey,
  ComponentState,
  Progress,
  State,
  cancelInstall,
  checkUpdates,
  getState,
  install,
  removeOldVersions,
  setAllowPrerelease,
} from "./backend";

const CHECK_INTERVAL_MS = 10 * 60 * 1000;
let lastCheck = 0;

const mb = (bytes: number) => `${(bytes / 1048576).toFixed(0)} MB`;

const STAGE_TEXT: Record<Progress["stage"], string> = {
  downloading: "Downloading",
  verifying: "Verifying checksum",
  installing: "Extracting and installing",
  done: "Done",
  cancelled: "Cancelled",
  error: "Failed",
};

function ComponentSection({
  state,
  progress,
  onState,
}: {
  state: ComponentState;
  progress: Progress | null;
  onState: (s: State) => void;
}) {
  const { latest } = state;
  const old = state.installed.slice(1);
  const active = state.busy && progress && !["done", "cancelled", "error"].includes(progress.stage);

  let action = "Install";
  if (latest && state.latest_installed) action = `Reinstall ${latest.version}`;
  else if (latest && state.current) action = `Update to ${latest.version}`;
  else if (latest) action = `Install ${latest.version}`;

  return (
    <PanelSection title={state.label}>
      <PanelSectionRow>
        <Field label="Installed" bottomSeparator="none">
          {state.current ?? "Not installed"}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <Field
          label="Latest"
          bottomSeparator="none"
          description={state.error ?? undefined}
        >
          {latest ? `${latest.version}${latest.prerelease ? " (pre-release)" : ""}` : "Unknown"}
        </Field>
      </PanelSectionRow>
      <PanelSectionRow>
        <ToggleField
          label="Allow pre-releases"
          checked={state.allow_prerelease}
          disabled={state.busy}
          onChange={async (value) => onState(await setAllowPrerelease(state.key, value))}
        />
      </PanelSectionRow>
      {active ? (
        <>
          <PanelSectionRow>
            <div style={{ width: "100%" }}>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "12px", marginBottom: "4px" }}>
                <span>{STAGE_TEXT[progress!.stage]}</span>
                {progress!.stage === "downloading" && progress!.total ? (
                  <span>{`${mb(progress!.done)} / ${mb(progress!.total)}`}</span>
                ) : null}
              </div>
              <ProgressBar
                indeterminate={progress!.stage !== "downloading" || !progress!.total}
                nProgress={progress!.total ? (progress!.done / progress!.total) * 100 : 0}
              />
            </div>
          </PanelSectionRow>
          <PanelSectionRow>
            <ButtonItem
              layout="below"
              disabled={progress!.stage !== "downloading"}
              onClick={async () => onState(await cancelInstall(state.key))}
            >
              Cancel
            </ButtonItem>
          </PanelSectionRow>
        </>
      ) : (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={!latest || state.busy}
            description={latest?.size ? `Download size ${mb(latest.size)}` : undefined}
            onClick={async () => onState(await install(state.key))}
          >
            {state.latest_installed || !state.update_available ? action : `${action} ●`}
          </ButtonItem>
        </PanelSectionRow>
      )}
      {state.key === "proton" && old.length > 0 && (
        <PanelSectionRow>
          <ButtonItem
            layout="below"
            disabled={state.busy}
            description={`Keeps ${state.current}, removes ${old.map((i) => i.version).join(", ")}`}
            onClick={() =>
              showModal(
                <ConfirmModal
                  strTitle="Remove old Proton versions?"
                  strDescription={
                    `This deletes ${old.map((i) => i.name).join(", ")}. ` +
                    "Games set to one of these will need a different compatibility tool. " +
                    "Restart Steam afterwards."
                  }
                  strOKButtonText="Remove"
                  bDestructiveWarning
                  onOK={async () => onState(await removeOldVersions(state.key))}
                />,
              )
            }
          >
            {`Remove old versions (${old.length})`}
          </ButtonItem>
        </PanelSectionRow>
      )}
    </PanelSection>
  );
}

function Content() {
  const [state, setState] = useState<State | null>(null);
  const [progress, setProgress] = useState<Partial<Record<ComponentKey, Progress>>>({});
  const [checking, setChecking] = useState(false);

  const applyState = useCallback((s: State) => {
    setState(s);
    setProgress((prev) => {
      const next = { ...prev };
      for (const key of Object.keys(s) as ComponentKey[]) {
        if (s[key].progress) next[key] = s[key].progress!;
      }
      return next;
    });
  }, []);

  const runCheck = useCallback(async () => {
    setChecking(true);
    try {
      applyState(await checkUpdates());
      lastCheck = Date.now();
    } finally {
      setChecking(false);
    }
  }, [applyState]);

  useEffect(() => {
    getState().then(applyState).catch(() => {});
    if (Date.now() - lastCheck > CHECK_INTERVAL_MS) runCheck().catch(() => {});

    const onProgress = addEventListener<[ComponentKey, Progress]>("dd_progress", (key, p) =>
      setProgress((prev) => ({ ...prev, [key]: p })),
    );
    const onChanged = addEventListener<[ComponentKey]>("dd_state_changed", () => {
      getState().then(applyState).catch(() => {});
    });
    return () => {
      removeEventListener("dd_progress", onProgress);
      removeEventListener("dd_state_changed", onChanged);
    };
  }, [applyState, runCheck]);

  if (!state) {
    return (
      <PanelSection>
        <PanelSectionRow>Loading…</PanelSectionRow>
      </PanelSection>
    );
  }

  return (
    <>
      <PanelSection>
        <PanelSectionRow>
          <ButtonItem layout="below" disabled={checking} onClick={runCheck}>
            {checking ? "Checking…" : "Check for updates"}
          </ButtonItem>
        </PanelSectionRow>
      </PanelSection>
      {(["proton", "turnip"] as ComponentKey[]).map((key) => (
        <ComponentSection key={key} state={state[key]} progress={progress[key] ?? null} onState={applyState} />
      ))}
    </>
  );
}

export default definePlugin(() => {
  // toasts live here so they still fire when the panel is closed mid-install
  const onProgress = addEventListener<[ComponentKey, Progress]>("dd_progress", (key, p) => {
    const label = key === "proton" ? "DroidDeck Proton" : "DroidDeck Turnip";
    if (p.stage === "done") {
      toaster.toast({
        title: `${label} installed`,
        body: key === "proton"
          ? "Restart Steam to see it in the compatibility tool list"
          : "Pick it under Drivers in Armada Control's Compatibility tab",
      });
    } else if (p.stage === "error") {
      toaster.toast({ title: `${label} install failed`, body: "Open Droid Deck Loader for details" });
    }
  });

  return {
    name: "Droid Deck Loader",
    titleView: <div className={staticClasses.Title}>Droid Deck Loader</div>,
    content: <Content />,
    icon: (
      <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
        <rect x="2" y="11" width="20" height="10" rx="4" />
        <path d="M12 2v11" />
        <path d="m8.5 9.5 3.5 3.5 3.5-3.5" />
      </svg>
    ),
    onDismount() {
      removeEventListener("dd_progress", onProgress);
    },
  };
});
