# Phase 0 behavioral-reference manifest

The v2 clean-break rebuild uses the frozen v1 tree only as an external behavioral oracle. It is
not imported, vendored, migrated, or loaded by the v2 runtime.

| Item | Frozen reference |
| --- | --- |
| Git tag | `v1-behavioral-reference-2026-08-17` |
| Commit | `93e02846e4d73097afc65f2dfd684a8a7e49966b` |
| Commit subject | `fix: close authorization and save-portability gaps (#63)` |
| V1 automated evidence | `tests/`, including contract, integration, service, and browser journeys |
| V1 fixtures | `tests/integration/fixtures/` plus fixtures declared by `tests/conftest.py` |
| V1 release evidence | `docs/release/` |
| V1 release bundle | `release/TableTopDM-v1.0.0.zip` |
| Bundle checksum manifest | `release/checksums.txt` |

The tag and commit must resolve to the same object:

```powershell
git rev-parse "v1-behavioral-reference-2026-08-17^{commit}"
git show -s --format="%H %s" v1-behavioral-reference-2026-08-17
```

Expected commit:

```text
93e02846e4d73097afc65f2dfd684a8a7e49966b
```

Verify that the oracle assets remain retrievable without changing the current checkout:

```powershell
git cat-file -e "v1-behavioral-reference-2026-08-17:tests/conftest.py"
git cat-file -e "v1-behavioral-reference-2026-08-17:tests/integration/fixtures/rag_doc.txt"
git cat-file -e "v1-behavioral-reference-2026-08-17:docs/release/1.0-golden-path-manual-qa.md"
git cat-file -e "v1-behavioral-reference-2026-08-17:release/TableTopDM-v1.0.0.zip"
git show "v1-behavioral-reference-2026-08-17:release/checksums.txt"
```

To inspect or execute the frozen oracle, use an isolated worktree:

```powershell
git worktree add ..\TableTop_DM-v1 v1-behavioral-reference-2026-08-17
git -C ..\TableTop_DM-v1 rev-parse HEAD
```

The expected bundle SHA-256 in the frozen manifest is:

```text
5E3BAADC55CDBC5C36A9454254C6B28D26910F621D2C68F6A746AB4759C7AA4D
```

After creating the worktree, verify it with:

```powershell
(Get-FileHash ..\TableTop_DM-v1\release\TableTopDM-v1.0.0.zip -Algorithm SHA256).Hash
```

The v1 release instructions and historical test matrix remain authoritative for v1 itself. V2
tests reproduce the required behavior through v2 contracts; they must not make the v2 build or
runtime depend on the worktree, tag, zip, or any v1 package.
