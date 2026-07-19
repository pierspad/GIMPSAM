## 1.0.0 (2026-07-19)

### ⚠ BREAKING CHANGES

* the old single-file wizard and its flags are gone;
the GUI now requires customtkinter (the prebuilt binary ships it).
* release asset set and .releaserc pipeline redesigned;
consumers should pin a release tag (LazyGimp does).

### ✨ Features

* add shortcuts, preselected defaults, collapsible categories, and gimp check at startup ([4a159a0](https://github.com/pierspad/GIMPSAM/commit/4a159a08e68f96d9417f2cab08681792866e1d1d))
* extract the SAM backend into an importable gimpsam package + full release pipeline ([2617197](https://github.com/pierspad/GIMPSAM/commit/261719725bf10398df59e5ed861f4ac63cf3500c))
* replace the legacy Tk wizard with LazyGimp's CustomTkinter GUI ([0dcd26e](https://github.com/pierspad/GIMPSAM/commit/0dcd26ed0e7dc572da6cdf3f419a26587057a538))
