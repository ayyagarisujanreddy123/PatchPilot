/**
 * Demo-only controls: fleet reset and seeded fault toggle.
 */

import { clearElement, el } from "../util.js";

const RESET_CONFIRM =
    "Reset the project fleet to the vulnerable baseline? This does not affect sites outside PatchPilot.";

export function renderDemoControls(root, snapshot, handlers) {
    clearElement(root);
    const { busy, ui } = snapshot;
    const disabled = busy || ui.preparing || ui.resetting || ui.approvalSubmitting;
    const mock = snapshot.health?.mode === "MOCK";

    const seedId = "demo-seed-fault";
    const clearMemoryId = "demo-clear-memory";

    const seedCheckbox = el("input", {
        id: seedId,
        className: "demo-controls__checkbox",
        attrs: {
            type: "checkbox",
            disabled: disabled ? "disabled" : undefined,
            checked: ui.seedFault ? "checked" : undefined,
        },
    });
    seedCheckbox.addEventListener("change", () => {
        handlers.onSeedFaultChange(seedCheckbox.checked);
    });

    const clearMemoryCheckbox = el("input", {
        id: clearMemoryId,
        className: "demo-controls__checkbox",
        attrs: {
            type: "checkbox",
            disabled: disabled ? "disabled" : undefined,
        },
    });

    const resetBtn = el(
        "button",
        {
            className: "btn btn--secondary demo-controls__reset",
            attrs: {
                type: "button",
                id: "reset-fleet",
                disabled: disabled ? "disabled" : undefined,
                "aria-disabled": disabled ? "true" : "false",
            },
        },
        ui.resetting ? "Resetting project fleet…" : "Reset fleet",
    );
    resetBtn.addEventListener("click", () => {
        if (disabled) {
            return;
        }
        if (!window.confirm(RESET_CONFIRM)) {
            return;
        }
        handlers.onResetFleet(clearMemoryCheckbox.checked);
    });

    const fieldset = el(
        "fieldset",
        {
            className: "demo-controls__fieldset",
            attrs: { disabled: disabled ? "disabled" : undefined },
        },
        [
            el("legend", { className: "demo-controls__legend" }, "Deliberately injected faults (demo)"),
            el("label", { className: "demo-controls__label", attrs: { for: seedId } }, [
                seedCheckbox,
                el("span", {}, "Seed incompatible candidate (2M upload limit on upload sites)"),
            ]),
            el(
                "p",
                { className: "demo-controls__hint" },
                "When enabled, the next repair passes seed_fault to staging. Staging rejection is separate from live rollback.",
            ),
        ],
    );

    root.append(
        el(
            "p",
            { className: "demo-controls__intro" },
            "For hackathon demos only. Controls are disabled while a repair or reset is in progress.",
        ),
        mock ? fieldset : el("p", { className: "demo-controls__hint" }, "Fault playback is available only in simulated demo data. Live repairs use the assessed security policy and actual verification evidence."),
        el("div", { className: "demo-controls__reset-block" }, [
            el("label", { className: "demo-controls__label", attrs: { for: clearMemoryId } }, [
                clearMemoryCheckbox,
                el("span", {}, "Also clear recipe memory"),
            ]),
            el(
                "p",
                { className: "demo-controls__hint" },
                "Restores the project fleet only. Completed run records are retained.",
            ),
            resetBtn,
        ]),
    );

    if (disabled) {
        root.append(
            el("p", { className: "hint hint--disabled", attrs: { role: "status" } }, "Disabled while PatchPilot is busy."),
        );
    }
}
