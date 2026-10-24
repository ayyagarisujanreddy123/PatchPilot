import { el } from "../util.js";

export function repositorySetupInstructions() {
    const manifest = { schemaVersion: 1, siteId: "your-site-identity", documentRoot: "public", phpIni: "php.ini", capabilities: ["homepage", "contact", "upload"], homepage: "/", contact: "/contact.php", upload: "/upload.php" };
    const marker = { repository: "OWNER/REPOSITORY", commit: "REPLACE_WITH_40_CHARACTER_DEFAULT_BRANCH_HEAD_SHA", siteId: "your-site-identity" };
    return el("details", { className: "repository-repair__disclosure", id: "repository-setup" }, [
        el("summary", { id: "repository-setup-summary" }, "Repository not supported yet? View setup requirements"),
        el("div", { className: "repository-repair__instructions" }, [
            el("p", {}, "You need push access through GitHub authentication configured on this computer. PatchPilot does not request an OAuth token in this form."),
            el("p", {}, "Add a .patchpilot.json manifest at the repository root. Use paths and capabilities that match your site. Homepage is required; contact and upload need the supported JSON response contracts."),
            el("pre", {}, el("code", {}, JSON.stringify(manifest, null, 2))),
            el("p", {}, "Serve /.well-known/patchpilot.json from the assessed website with the same siteId, selected repository, and its exact default branch HEAD commit. Replace the template values below."),
            el("pre", {}, el("code", {}, JSON.stringify(marker, null, 2))),
            el("p", {}, "The marker is a declared deployment identity, not independent build attestation. Repository scripts, installers, and Dockerfiles are not run. Only supported PHP error-display, logging, and version-banner settings can be changed."),
        ]),
    ]);
}

function capability(id, label, checked, disabled, callback) {
    const input = el("input", { id, attrs: { type: "checkbox", checked: checked ? "checked" : undefined, disabled: disabled ? "disabled" : undefined } });
    input.addEventListener("change", () => callback(input.checked));
    return el("label", { className: "repository-repair__checkbox", attrs: { for: id } }, [input, label]);
}

export function repositoryConnectForm(snapshot, assessmentId, data, handlers) {
    const draft = snapshot.ui.repositoryDrafts[assessmentId] ?? {};
    const status = snapshot.repositoryGitHubStatus;
    const sample = (snapshot.websiteExamples ?? []).find((item) => item.url === snapshot.websiteReports[assessmentId]?.url);
    const busy = Boolean(data.busyAction);
    const input = el("input", { id: "repository-url", attrs: { type: "url", required: "required", maxlength: 2048, placeholder: "https://github.com/owner/repository", autocomplete: "url", spellcheck: "false", value: draft.url ?? sample?.repositoryUrl ?? "", "aria-describedby": "repository-url-hint", disabled: busy ? "disabled" : undefined } });
    input.addEventListener("input", () => handlers.onDraft(assessmentId, { url: input.value }));
    const form = el("form", { id: "repository-connect-form", className: "repository-repair__form" }, [
        el("p", { id: "repository-github-status", className: "repository-repair__account", attrs: { role: "status" } }, !status ? "Checking GitHub authentication on this computer…" : status.available ? `GitHub account on this computer${status.login ? `: ${status.login}` : " is available"}. ${status.message}` : status.message),
        el("label", { attrs: { for: "repository-url" } }, "GitHub repository URL"), input,
        el("p", { id: "repository-url-hint", className: "muted" }, "Connect a repository you can push to. The website marker must match its current default branch commit."),
        el("fieldset", { attrs: { disabled: busy ? "disabled" : undefined } }, [el("legend", {}, "Business checks to preserve"),
            capability("repository-homepage", "Homepage (required)", true, true, () => {}),
            capability("repository-contact", "Contact submission", draft.contact !== false, false, (contact) => handlers.onDraft(assessmentId, { contact })),
            capability("repository-upload", "3 MiB upload with byte count & SHA-256", draft.upload !== false, false, (upload) => handlers.onDraft(assessmentId, { upload })),
        ]),
        el("p", { className: "muted" }, "Connecting verifies declared identity and selected checks. Preparing a candidate is a separate action."),
        el("button", { className: "btn btn--secondary", id: "repository-connect", attrs: { type: "submit", disabled: busy || !status?.available ? "disabled" : undefined } }, data.busyAction === "connect" ? "Connecting…" : "Connect repository"),
    ]);
    form.addEventListener("submit", (event) => { event.preventDefault(); handlers.onDraft(assessmentId, { url: input.value }); handlers.onConnect(assessmentId); });
    return form;
}
