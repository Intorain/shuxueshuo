"""Reference a run's immutable revision manifest without copying it into cards.

The run identity/frozen artifact owns the manifest. Execution checkpoints and new
cards carry only its canonical digest. Legacy cards keep their original content
and hash; reading them never rewrites an already published mathematical step.
"""

import re

from ...problem_understanding.identity import revision

_DIGEST = re.compile(r"[a-f0-9]{64}\Z")


def manifest_ref(manifest):
    if (not isinstance(manifest, dict) or not manifest
            or any(not isinstance(key, str) or not isinstance(value, str)
                   or not _DIGEST.fullmatch(value) for key, value in manifest.items())):
        raise ValueError("revisions.invalid_manifest")
    return revision(manifest)


def revision_ref(value):
    """Read either format, rejecting ambiguous or inconsistent dual identities."""
    reference = value.get("revisions_ref")
    if reference is not None and (not isinstance(reference, str) or not _DIGEST.fullmatch(reference)):
        raise ValueError("revisions.invalid_reference")
    if "revisions" in value:
        legacy = manifest_ref(value["revisions"])
        if reference is not None and reference != legacy:
            raise ValueError("revisions.reference_mismatch")
        return legacy
    if reference is None:
        raise ValueError("revisions.missing_reference")
    return reference


def validate_revision_ref(value, expected_manifest):
    if revision_ref(value) != manifest_ref(expected_manifest):
        raise ValueError("revisions.reference_mismatch")


# Readable aliases for projection callers; both use exactly the same validation.
reference = revision_ref
validate_reference = validate_revision_ref


def math_step_hash(fragment, expected_revisions=None):
    """Preserve v1 hashes byte-for-byte; v2 binds the compact manifest reference."""
    if expected_revisions is not None:
        validate_revision_ref(fragment, expected_revisions)
    content = {key: value for key, value in fragment.items() if key != "math_step_sha256"}
    contract = fragment.get("contract")
    if contract == "graph-math-step/v1":
        # This duplicate legacy envelope is intentional compatibility behavior.
        return revision({"content": content, "revisions": fragment["revisions"]})
    if contract != "graph-math-step/v2" or "revisions" in fragment:
        raise ValueError("revisions.invalid_math_step_contract")
    return revision({"content": content, "revisions_ref": revision_ref(fragment)})
