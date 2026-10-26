# Source-copy preparation

This copy is separated from the private working application. It includes application source, synthetic tests, build instructions, and a fictional Orchard Study project.

Excluded: original research data and catalogues, saved conversations and databases, native session workspaces, screenshots of private projects, historical validation logs, personal paths, compiled apps and local build configuration. Runtime state is generated only when a user opens a project. The public launcher has no automatic migration from a private workspace.

The graph model discovers folder structure and report references generically. It does not apply the original application's domain-specific classification. The default demo has two reproducible growth-model variants with code, small data tables, metadata and PNG figures.

Validation: 91 existing synthetic Python tests passed after generalization; the additional demo test passed, including deterministic regeneration and inspectable code/data/figure packages. Graph interaction and preview-layout JavaScript checks passed. The demo was opened in the UI and its figure preview verified. Source pattern checks and a separate known-private-identifier scan found no matches in distributable files.

Frontend smoke testing used locally available copies of the locked xterm dependencies. Fetching npm packages was unavailable in the test environment; a fresh online npm installation was not verified. Dependencies are excluded from the source archive.

Run `python3 audit_public.py` and `python3 package_source.py` before sharing. The ZIP excludes runtime state, caches, dependencies and native bundles. A scan cannot guarantee detection of all personal information added in future edits.

The copy uses MIT licensing with contributor attribution. Nothing has been uploaded or published.
