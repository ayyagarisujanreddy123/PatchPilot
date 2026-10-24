/**
 * Verified recipe memory panel (read-only).
 */

import { clearElement, el } from "../util.js";

function formatVerifiedAt(iso) {
    if (iso == null || iso === "") {
        return "—";
    }
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
        return String(iso);
    }
    return d.toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
    });
}

function renderFailureNotes(notes) {
    if (notes == null || notes === "") {
        return el("p", { className: "recipe-meta" }, "None recorded");
    }
    if (Array.isArray(notes)) {
        if (!notes.length) {
            return el("p", { className: "recipe-meta" }, "None recorded");
        }
        return el(
            "ul",
            { className: "recipe-notes" },
            notes.map((note) => el("li", {}, note == null ? "—" : String(note))),
        );
    }
    return el("p", { className: "recipe-meta" }, String(notes));
}

function renderRecipeCard(recipe, index) {
    const reuseCount = recipe.reuse_count;
    const reuseNote =
        reuseCount != null && Number(reuseCount) > 0
            ? el(
                  "p",
                  { className: "recipe-reuse-note" },
                  "Recipe reused on later sites; checks were re-run each time.",
              )
            : null;

    return el(
        "article",
        {
            className: "recipe-card",
            attrs: { "aria-labelledby": `recipe-title-${index}` },
        },
        [
            el("h3", { className: "recipe-card__title", id: `recipe-title-${index}` }, `Recipe ${index + 1}`),
            el("h4", { className: "recipe-card__subtitle" }, "Compatibility key"),
            el("pre", { className: "recipe-key" }, recipe.key_summary ?? "—"),
            el("dl", { className: "recipe-dl" }, [
                el("div", { className: "recipe-dl__row" }, [
                    el("dt", {}, "Originating site"),
                    el("dd", {}, recipe.origin_site ?? "—"),
                ]),
                el("div", { className: "recipe-dl__row" }, [
                    el("dt", {}, "Originating run"),
                    el("dd", {}, recipe.origin_run ?? "—"),
                ]),
                el("div", { className: "recipe-dl__row" }, [
                    el("dt", {}, "Verified at"),
                    el("dd", {}, formatVerifiedAt(recipe.verified_at)),
                ]),
                el("div", { className: "recipe-dl__row" }, [
                    el("dt", {}, "Reuse count"),
                    el("dd", {}, reuseCount == null ? "—" : String(reuseCount)),
                ]),
            ]),
            reuseNote,
            el("h4", { className: "recipe-card__subtitle" }, "Failure observations"),
            renderFailureNotes(recipe.failure_notes),
        ],
    );
}

export function renderRecipes(root, snapshot) {
    clearElement(root);
    const { recipes, ui } = snapshot;
    const list = recipes ?? [];

    root.append(el("h2", { className: "panel__title" }, "Recipe memory"));
    root.append(
        el(
            "p",
            { className: "panel__lede" },
            "Verified repair knowledge committed after activation checks pass. Compatibility keys exclude organization names and instance IDs.",
        ),
    );

    if (ui.loading) {
        root.append(el("p", { className: "panel__status", attrs: { role: "status" } }, "Loading recipes…"));
        return;
    }

    if (!list.length) {
        root.append(el("p", { className: "empty-state" }, "No verified recipes saved yet."));
        return;
    }

    root.append(
        el(
            "div",
            { className: "recipe-list", attrs: { role: "list" } },
            list.map((recipe, i) =>
                el("div", { className: "recipe-list__item", attrs: { role: "listitem" } }, [
                    renderRecipeCard(recipe, i),
                ]),
            ),
        ),
    );
}
