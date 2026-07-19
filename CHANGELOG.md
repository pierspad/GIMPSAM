## [1.1.0](https://github.com/pierspad/GIMPSAM/compare/v1.0.1...v1.1.0) (2026-07-19)

### ✨ Features

* implement dynamic SAM category reordering, arrow navigation, PageUp/PageDown, and category/model shortcuts ([2fde1d0](https://github.com/pierspad/GIMPSAM/commit/2fde1d03de4be1d609740a803200aa7be4220c93))

## [1.0.1](https://github.com/pierspad/GIMPSAM/compare/v1.0.0...v1.0.1) (2026-07-19)

### 🐛 Bug Fixes

* resolve NameError for F_ITEM_TITLE and fix black overlay bug on Linux ([6dd1086](https://github.com/pierspad/GIMPSAM/commit/6dd10860a5ebaf774f72ee37ec126cf1a7d1ba2b))

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
