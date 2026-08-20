# Changelog

## [0.1.3](https://github.com/serverkraken/deadmansnitch/compare/v0.1.2...v0.1.3) (2026-08-20)


### Bug Fixes

* **docker:** multi-stage build without pip/poetry in the runtime image ([#70](https://github.com/serverkraken/deadmansnitch/issues/70)) ([95be96d](https://github.com/serverkraken/deadmansnitch/commit/95be96d240f49d217261b2ce8e557c67eb4c09a7))

## [0.1.2](https://github.com/serverkraken/deadmansnitch/compare/v0.1.1...v0.1.2) (2026-08-20)


### Bug Fixes

* **docker:** apply Debian security upgrades during image build ([#68](https://github.com/serverkraken/deadmansnitch/issues/68)) ([8cd4204](https://github.com/serverkraken/deadmansnitch/commit/8cd4204b1cea500ca5d0c9fa0544956c35dab3ce))

## [0.1.1](https://github.com/serverkraken/deadmansnitch/compare/v0.1.0...v0.1.1) (2026-08-20)


### Bug Fixes

* resolve 10 confirmed findings from the main-branch code review ([#65](https://github.com/serverkraken/deadmansnitch/issues/65)) ([aa0f4b6](https://github.com/serverkraken/deadmansnitch/commit/aa0f4b64a7fc853f7536c38467f0fb7a98e45154))

## 0.1.0 (2026-08-18)


### Features

* add a README ([3c2cbd7](https://github.com/serverkraken/deadmansnitch/commit/3c2cbd71dc4f1a41c578aaf11ccf8d221f14cb3f))
* ai changes ([fd91b40](https://github.com/serverkraken/deadmansnitch/commit/fd91b4002ca29cdd92a1de9a06b81b583487df1f))
* more logging ([6510123](https://github.com/serverkraken/deadmansnitch/commit/651012379445691b821260102b622146e1bc2afa))
* periodic reminder ([2af9dec](https://github.com/serverkraken/deadmansnitch/commit/2af9dec549a60b717ebb7b68e2e138f46c447117))
* unify logging and increase test coverage to 87% ([04865e1](https://github.com/serverkraken/deadmansnitch/commit/04865e1c3a156b8e4c79c693e1b1e521dab3b391))
* update code ([1170062](https://github.com/serverkraken/deadmansnitch/commit/11700621d0b10c69652c1e5d2c33c6e9cc6c3cda))
* update code ([52f5d1e](https://github.com/serverkraken/deadmansnitch/commit/52f5d1e59713a04f500eb3a8b913d783bd7c6559))
* use sqlite3 db ([b72cf66](https://github.com/serverkraken/deadmansnitch/commit/b72cf66e5f1b7afab47fe0a5614ded9d3671b535))


### Bug Fixes

* a bug in check_watchdog ([8e07e03](https://github.com/serverkraken/deadmansnitch/commit/8e07e03673ac2a1ab7a75550640c35a16e741adf))
* add a startup grace period ([0698384](https://github.com/serverkraken/deadmansnitch/commit/0698384421467d27ca1da53728e56ba7baebcfae))
* add readiness and liveness endpoints ([6fb98ee](https://github.com/serverkraken/deadmansnitch/commit/6fb98eeb063d77afbf45cba22a6404a759048715))
* add renovate config ([a0fa1e9](https://github.com/serverkraken/deadmansnitch/commit/a0fa1e9ff9e54623d978be507d8a39c0a2c160fc))
* adjust logging ([81e14ec](https://github.com/serverkraken/deadmansnitch/commit/81e14ecbe109327bbde7f2d8cf1283c88c922f46))
* configure logging ([1c8e27a](https://github.com/serverkraken/deadmansnitch/commit/1c8e27a56b2c4b879cfcb24dd4953024966f7fb8))
* **deps:** bump urllib3 to 2.7.0 to unblock the release PR ([#64](https://github.com/serverkraken/deadmansnitch/issues/64)) ([986f805](https://github.com/serverkraken/deadmansnitch/commit/986f805713968a0bcf661fa05ce4518a344b8dad))
* formatting ([8985625](https://github.com/serverkraken/deadmansnitch/commit/8985625bfd96996ef8ebf1b53cc0351520f2a498))
* gunicorn ([415f12e](https://github.com/serverkraken/deadmansnitch/commit/415f12e543aeeef34ed633221d9886f0e9100eb5))
* initial commit ([5c29a78](https://github.com/serverkraken/deadmansnitch/commit/5c29a787d5fac6b514379ce33dddd47a5070e89d))
* Initialize watchdogservice only once, synchronize is_healthy and status field ([1112c26](https://github.com/serverkraken/deadmansnitch/commit/1112c26a719fba6c0e15a6b6dab372ca83d53f75))
* locking ([559bbd5](https://github.com/serverkraken/deadmansnitch/commit/559bbd569096e06ffc5cd57a38c60ef39064f7c5))
* locking problem ([11a7c6b](https://github.com/serverkraken/deadmansnitch/commit/11a7c6bcec738e55cba9ad236cb848b392087b05))
* logging frequency ([d492fb1](https://github.com/serverkraken/deadmansnitch/commit/d492fb1aef074528d44382d914d9e7d2e9c46fcc))
* logic ([ad07aab](https://github.com/serverkraken/deadmansnitch/commit/ad07aabfadda5c3620904276217d5bc947a002db))
* logic errors ([6665978](https://github.com/serverkraken/deadmansnitch/commit/66659781ea37211e69a7d51a993cb01b9d177481))
* make app more functional ([947dfa1](https://github.com/serverkraken/deadmansnitch/commit/947dfa1a476ae1c12e08292246aa3716c44d4516))
* new build ([1810c58](https://github.com/serverkraken/deadmansnitch/commit/1810c58eeda947894b308e65bb9376718c2e7aec))
* readme [skip ci] ([1e06687](https://github.com/serverkraken/deadmansnitch/commit/1e06687643df99e0fc0bf566239936a048cc73ce))
* refresh state in monitor, too ([1bd9ba8](https://github.com/serverkraken/deadmansnitch/commit/1bd9ba8107158d35a184c2d8966e005e1657c25b))
* remove data file ([fbaeb61](https://github.com/serverkraken/deadmansnitch/commit/fbaeb61b2f986bf564a665cb38d753c04cae835f))
* Reset Status upon Message Receipt ([4f3ad3d](https://github.com/serverkraken/deadmansnitch/commit/4f3ad3d6d7a53ee6487aebef173b9d5c6fc021e9))
* singleton, and state_lock ([5009b95](https://github.com/serverkraken/deadmansnitch/commit/5009b95feaaf56dae39054089f0c718b7d5200ad))
* smaller interval of checks ([1c6931d](https://github.com/serverkraken/deadmansnitch/commit/1c6931d1a46c9ac209b18263523b4909e9cc4ff7))
* use caching ([276073b](https://github.com/serverkraken/deadmansnitch/commit/276073b48648f18c9615f41b32deecf7745ec336))
* use my Dockerfile ([3834e40](https://github.com/serverkraken/deadmansnitch/commit/3834e406e4ee1f57154c28e8c6818c4b35bc4cb7))
* use old jsonify syntax again ([7f755ca](https://github.com/serverkraken/deadmansnitch/commit/7f755ca83125747304d5e411f14bac89ee9116be))
