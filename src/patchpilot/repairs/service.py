"""Connect a declared deployment, independently stage its patch, then publish explicitly."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from patchpilot.repairs.configuration import (
    apply_changes,
    inspect_ini,
    is_secure,
)
from patchpilot.repairs.errors import ConnectedRepairError
from patchpilot.repairs.github import GitHubClient, checked_sha, repository_name
from patchpilot.repairs.models import (
    GitHubStatus,
    RepairEvent,
    RepositoryConnection,
    RepositoryPatch,
    RepositoryRepairReport,
    SiteManifest,
)
from patchpilot.repairs.planner import AnthropicConfigPlanner
from patchpilot.webscan.network import PublicHTTPClient, PublicHTTPError

SECURITY = {
    "display_errors",
    "display_startup_errors",
    "log_errors",
    "expose_php",
    "php_banner_hidden",
}
BUSINESS = {
    "homepage": {"homepage_status"},
    "contact": {"contact_valid", "contact_invalid"},
    "upload": {"upload_size", "upload_sha256"},
}


def now():
    return datetime.now(UTC).isoformat()


def fresh(timestamp):
    try:
        age = (datetime.now(UTC) - datetime.fromisoformat(timestamp)).total_seconds()
        return 0 <= age <= 3600
    except (TypeError, ValueError):
        return False


def _origin(url):
    parsed = urlsplit(url)
    return (
        parsed.scheme,
        parsed.hostname,
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )


class RepositoryRepairService:
    def __init__(
        self,
        root=None,
        *,
        github_factory=None,
        public_client=None,
        sandbox=None,
        planner_factory=None,
    ):
        self.root = Path(root or Path(__file__).resolve().parents[3])
        self.github_factory = github_factory or (
            lambda: GitHubClient.from_environment(self.root)
        )
        self.public_client = public_client or PublicHTTPClient()
        self.sandbox = sandbox
        self.planner_factory = planner_factory or (
            lambda: AnthropicConfigPlanner.from_environment(self.root)
        )

    def status(self):
        github = None
        try:
            github = self.github_factory()
            return GitHubStatus(
                available=True,
                login=github.identity(),
                message="Using the GitHub account signed in on this computer. Choose a repository you control.",
            )
        except (ConnectedRepairError, OSError, RuntimeError):
            return GitHubStatus(
                available=False,
                message="Sign in with gh auth login on this computer, or configure GITHUB_TOKEN locally. Never paste a token into the website URL.",
            )
        finally:
            if github is not None:
                github.close()

    def _identity(self, url, repository, commit, site_id):
        parsed = urlsplit(url)
        marker_url = urlunsplit(
            (parsed.scheme, parsed.netloc, "/.well-known/patchpilot.json", "", "")
        )
        try:
            responses = self.public_client.fetch(
                marker_url, timeout_s=15, max_redirects=2
            )
            final = responses[-1]
            if (
                any(_origin(item.url) != _origin(url) for item in responses)
                or final.status != 200
                or final.body_truncated
                or len(final.body) > 16384
            ):
                raise ValueError("Invalid deployment marker response")
            data = json.loads(final.body)
            if (
                not isinstance(data, dict)
                or set(data) != {"repository", "commit", "siteId"}
                or str(data["repository"]).lower() != repository.lower()
                or data["commit"] != commit
                or data["siteId"] != site_id
            ):
                raise ValueError("Deployment identity mismatch")
        except (PublicHTTPError, ValueError, IndexError):
            raise ConnectedRepairError(
                "The website's deployment marker is missing or does not match this repository's current commit. Add /.well-known/patchpilot.json with repository, commit, and siteId, then assess and connect the deployed version again."
            ) from None

    @staticmethod
    def _manifest(github, repository, commit):
        raw, _ = github.read_file(repository, ".patchpilot.json", commit, limit=16384)
        try:
            return SiteManifest.model_validate_json(raw)
        except ValueError:
            raise ConnectedRepairError(
                "Add a valid .patchpilot.json supported PHP profile to the repository. Use the supplied community-site example."
            ) from None

    def connect(self, assessment, repository_url, capabilities):
        if (
            assessment.state != "COMPLETED"
            or not assessment.finished_at
            or not fresh(assessment.finished_at)
        ):
            raise ConnectedRepairError(
                "Complete a fresh website assessment within the last hour before connecting a repository."
            )
        if urlsplit(assessment.url).path not in {"", "/"}:
            raise ConnectedRepairError(
                "This first connected profile supports the website home URL. Assess the origin's homepage first."
            )
        repository = repository_name(repository_url)
        github = self.github_factory()
        try:
            with github.budget(35):
                branch, commit = github.repository(repository)
                manifest = self._manifest(github, repository, commit)
                selected = list(dict.fromkeys(capabilities))
                if (
                    "homepage" not in selected
                    or not set(selected) <= set(manifest.capabilities)
                    or len(selected) != len(capabilities)
                ):
                    raise ConnectedRepairError(
                        "Choose homepage and only the business checks declared by this repository's PHP profile."
                    )
                raw, _ = github.read_file(
                    repository, manifest.php_ini, commit, limit=16384
                )
                inspect_ini(raw.decode("utf-8"))
                self._identity(assessment.url, repository, commit, manifest.site_id)
            return RepositoryConnection(
                connection_id=f"connection-{uuid4().hex}",
                assessment_id=assessment.assessment_id,
                url=assessment.url,
                repository=repository,
                repository_url=f"https://github.com/{repository}",
                default_branch=branch,
                base_commit=commit,
                site_id=manifest.site_id,
                manifest=manifest,
                capabilities=selected,
                created_at=now(),
            )
        except UnicodeError:
            raise ConnectedRepairError(
                "The PHP configuration must be UTF-8 text."
            ) from None
        finally:
            github.close()

    def _sandbox(self):
        if self.sandbox is None:
            from patchpilot.repairs.sandbox import DockerSandbox

            self.sandbox = DockerSandbox(self.root)
        return self.sandbox

    @staticmethod
    def _check_phase(result, phase, capabilities, *, secure):
        business = set().union(*(BUSINESS[capability] for capability in capabilities))
        required = SECURITY | business | {"runtime_version"}
        ids = [check.check_id for check in result.checks]
        if (
            len(ids) != len(set(ids))
            or set(ids) != required
            or any(check.phase != phase for check in result.checks)
        ):
            raise ConnectedRepairError(
                "The verifier returned incomplete or duplicate assertions. No repair was accepted."
            )
        necessary = required if secure else business | {"runtime_version"}
        return all(
            check.passed is True
            for check in result.checks
            if check.check_id in necessary
        )

    def repair(self, connection, *, repair_id, emit):
        report = RepositoryRepairReport(
            repair_id=repair_id,
            connection_id=connection.connection_id,
            assessment_id=connection.assessment_id,
            repository=connection.repository,
            url=connection.url,
            base_commit=connection.base_commit,
            created_at=now(),
            capabilities=connection.capabilities,
        )

        def publish(state, message):
            report.state, report.stage_message = state, message
            report.events.append(
                RepairEvent(
                    sequence=len(report.events) + 1,
                    timestamp=now(),
                    state=state,
                    message=message,
                )
            )
            emit(report.model_copy(deep=True))

        github = None
        try:
            if not fresh(connection.created_at):
                raise ConnectedRepairError(
                    "This repository connection expired. Reconnect the current deployment before testing a repair."
                )
            publish(
                "FETCHING",
                "Confirming the deployed commit and fetching bounded PHP source from GitHub",
            )
            github = self.github_factory()
            with github.budget(45):
                if github.repository(connection.repository) != (
                    connection.default_branch,
                    connection.base_commit,
                ):
                    raise ConnectedRepairError(
                        "The repository changed after connection. Reconnect its current deployed commit."
                    )
                manifest = self._manifest(
                    github, connection.repository, connection.base_commit
                )
                if manifest != connection.manifest:
                    raise ConnectedRepairError(
                        "The repository profile changed after connection."
                    )
                self._identity(
                    connection.url,
                    connection.repository,
                    connection.base_commit,
                    connection.site_id,
                )
                raw, before_blob = github.read_file(
                    connection.repository,
                    manifest.php_ini,
                    connection.base_commit,
                    limit=16384,
                )
                original = raw.decode("utf-8")
                settings = inspect_ini(original)
                files = github.source_files(
                    connection.repository,
                    manifest.document_root,
                    connection.base_commit,
                )
            publish(
                "BASELINE",
                "Testing the original repository copy: PHP settings and the website functions you selected",
            )
            baseline = self._sandbox().verify(
                files,
                original,
                manifest,
                connection.capabilities,
                "BASELINE",
                run_id=repair_id,
            )
            report.checks.extend(baseline.checks)
            report.image_digest = baseline.image_digest
            if not self._check_phase(
                baseline, "BASELINE", connection.capabilities, secure=False
            ):
                report.finished_at = now()
                publish(
                    "REJECTED",
                    "The original copy failed a required website-function check. Fix the baseline before preparing a security change.",
                )
                return report
            if is_secure(settings):
                report.finished_at = now()
                publish(
                    "NO_CHANGE",
                    "The repository already has the supported secure settings. No patch or pull request was created.",
                )
                return report
            publish(
                "PLANNING",
                "Victor is preparing a bounded PHP configuration change",
            )
            planner = self.planner_factory()
            try:
                report.proposal = planner.propose(
                    settings=settings,
                    runtime=baseline.runtime,
                    checks=baseline.checks,
                    capabilities=connection.capabilities,
                    progress=lambda message: publish("PLANNING", message),
                )
            finally:
                planner.close()
            candidate, diff = apply_changes(
                original, report.proposal.changes, manifest.php_ini
            )
            report.patch = RepositoryPatch(
                path=manifest.php_ini,
                before_blob_sha=before_blob,
                after_sha256=hashlib.sha256(candidate.encode()).hexdigest(),
                unified_diff=diff,
            )
            publish(
                "STAGING",
                "Testing the exact proposed configuration in a second isolated PHP container",
            )
            result = self._sandbox().verify(
                files,
                candidate,
                manifest,
                connection.capabilities,
                "CANDIDATE",
                run_id=repair_id,
            )
            report.checks.extend(result.checks)
            if result.image_digest != baseline.image_digest or not self._check_phase(
                result, "CANDIDATE", connection.capabilities, secure=True
            ):
                report.finished_at = now()
                publish(
                    "REJECTED",
                    "The candidate failed independent security or website-function checks. No pull request can be created.",
                )
                return report
            report.finished_at = now()
            publish(
                "READY_TO_PUBLISH",
                "The isolated candidate passed every required check. Review its change and evidence before creating a draft pull request.",
            )
        except ConnectedRepairError as error:
            report.error, report.finished_at = str(error), now()
            publish("FAILED", report.error)
        except (OSError, ValueError, RuntimeError, TypeError, KeyError):
            report.error, report.finished_at = (
                "The connected repair could not finish. Collected evidence was retained; no successful fix was fabricated.",
                now(),
            )
            publish("FAILED", report.error)
        finally:
            if github is not None:
                github.close()
        return report

    def publish(self, connection, report, *, emit):
        if (
            report.state not in {"PUBLISHING", "READY_TO_PUBLISH", "PUBLISHED"}
            or report.connection_id != connection.connection_id
            or report.repository != connection.repository
            or report.base_commit != connection.base_commit
            or report.capabilities != connection.capabilities
            or report.patch is None
            or report.proposal is None
            or report.patch.path != connection.manifest.php_ini
        ):
            raise ConnectedRepairError(
                "Only this connection's exact verified patch can be published."
            )
        for phase in ("BASELINE", "CANDIDATE"):
            from patchpilot.repairs.models import SandboxResult

            result = SandboxResult(
                tuple(check for check in report.checks if check.phase == phase),
                {},
                report.image_digest or "",
            )
            if not self._check_phase(
                result, phase, connection.capabilities, secure=phase == "CANDIDATE"
            ):
                raise ConnectedRepairError(
                    "Publication requires complete, passing website and candidate-security evidence."
                )
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", report.image_digest or ""):
            raise ConnectedRepairError(
                "The verified staging image identity is missing."
            )
        github = self.github_factory()
        try:
            with github.budget(45):
                raw, before_blob = github.read_file(
                    connection.repository,
                    connection.manifest.php_ini,
                    connection.base_commit,
                    limit=16384,
                )
                candidate, diff = apply_changes(
                    raw.decode("utf-8"),
                    report.proposal.changes,
                    connection.manifest.php_ini,
                )
                if (
                    before_blob != report.patch.before_blob_sha
                    or hashlib.sha256(candidate.encode()).hexdigest()
                    != report.patch.after_sha256
                    or diff != report.patch.unified_diff
                ):
                    raise ConnectedRepairError(
                        "The publication content differs from the candidate that passed verification."
                    )
                body = self._pull_request_body(report)
                pull = github.publish_patch(
                    repository=connection.repository,
                    base_branch=connection.default_branch,
                    base_commit=checked_sha(connection.base_commit),
                    repair_id=report.repair_id,
                    path=report.patch.path,
                    candidate=candidate.encode(),
                    body=body,
                    allow_create=fresh(connection.created_at)
                    and fresh(report.created_at),
                )
            report.pull_request, report.state, report.error = pull, "PUBLISHED", None
            report.finished_at = now()
            report.stage_message = "Draft pull request created with the exact verified patch and test evidence. The live website has not been changed."
            report.events.append(
                RepairEvent(
                    sequence=len(report.events) + 1,
                    timestamp=now(),
                    state="PUBLISHED",
                    message=report.stage_message,
                )
            )
            emit(report.model_copy(deep=True))
            return report
        finally:
            github.close()

    @staticmethod
    def _pull_request_body(report):
        lines = [
            "## PHP configuration repair",
            "",
            "This one-file change hardens PHP error display/logging and version disclosure. Upload limits and application source are unchanged.",
            "",
            f"Verified base commit: `{report.base_commit}`",
            f"Candidate configuration SHA-256: `{report.patch.after_sha256}`",
            f"Staging PHP image: `{report.image_digest}`",
            "",
            "### Independent checks",
            "",
            "| Phase | Check | Result |",
            "| --- | --- | --- |",
        ]
        lines.extend(
            f"| {check.phase} | {check.check_id} | {'PASS' if check.passed else 'FAIL (baseline finding)'} |"
            for check in report.checks
        )
        if "contact" in report.capabilities:
            lines.extend(
                [
                    "",
                    "The contact check validates form responses; it does not verify email delivery.",
                ]
            )
        if "upload" in report.capabilities:
            lines.extend(
                [
                    "",
                    "The upload check sends a real 3 MiB payload and verifies byte count and SHA-256.",
                ]
            )
        lines.extend(
            [
                "",
                "Victor (powered by Anthropic) proposed the allowlisted settings; fixed independent checks accepted the candidate. No model commands were executed.",
                "",
                "This proof covers an isolated reconstruction of the declared source commit. This PR has not been deployed and does not claim the live website is repaired.",
                "",
                f"PatchPilot repair: `{report.repair_id}`",
            ]
        )
        return "\n".join(lines)
