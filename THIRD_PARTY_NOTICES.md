# Third-party notices

The optional Xiaohongshu fetch path checks out selected runtime components from:

- `yzbcs/Daily-Digest-Assistant`, commit `4957c3e40354816edbb2114e3aad7a3b53be47d4`
- Copyright (c) 2026 yzbcs
- License: MIT

The upstream copyright and permission notice remain available in its
[`LICENSE`](https://github.com/yzbcs/Daily-Digest-Assistant/blob/main/LICENSE).
The dependency is used only at GitHub Actions runtime and is not copied into
PaperLearning Vault.

The optional Zhihu fetch path checks out one signing runtime file from:

- `NanmiCoder/MediaCrawler`, commit `0625e01a6bc717a3fc9c96d3dac7fb8957043838`
- File: `libs/zhihu.js`
- Copyright (c) 2025 relakkes@gmail.com and its acknowledged upstream authors
- License: NON-COMMERCIAL LEARNING LICENSE 1.1

The upstream copyright, usage restrictions, and license remain available in its
[`LICENSE`](https://github.com/NanmiCoder/MediaCrawler/blob/main/LICENSE).
The runtime is used only for low-frequency, read-only personal learning at
GitHub Actions runtime and is not copied into this repository or PaperLearning
Vault.

The optional X fetch path uses:

- [`d60/twikit`](https://github.com/d60/twikit), based on version `2.3.3`
- Temporary compatibility patch:
  [`d60/twikit#419`](https://github.com/d60/twikit/pull/419), commit
  `e9b5acf140492fb642b2e5322a9ad55ee10415bc`
- Copyright (c) d60 and contributors
- License: MIT

Twikit is used for low-frequency, read-only search with a user-provided session
Cookie. PaperLearning does not call its posting or engagement methods. The
compatibility commit is pinned because the current PyPI release predates X's
2026 SearchTimeline and client-transaction changes.
