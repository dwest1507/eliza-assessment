# Changelog

## [0.4.0](https://github.com/dwest1507/eliza-assessment/compare/eliza-assessment-v0.3.1...eliza-assessment-v0.4.0) (2026-10-19)


### Features

* **eval:** decide retrieval comparisons on Fact Recall fact by fact ([a39eb0d](https://github.com/dwest1507/eliza-assessment/commit/a39eb0d61886657c4a48666a1db9a8d636618682)), closes [#118](https://github.com/dwest1507/eliza-assessment/issues/118)
* **export:** show the Arm and settings comparisons fact by fact ([7c285ff](https://github.com/dwest1507/eliza-assessment/commit/7c285ffb2c14276928d4503e2b188d8b3dde1b94)), closes [#131](https://github.com/dwest1507/eliza-assessment/issues/131)
* **retrieval:** a topic table adds the Filings' own wording to the search ([9d601e5](https://github.com/dwest1507/eliza-assessment/commit/9d601e51a565dcce4ae91044b97c15ddb35e7588)), closes [#125](https://github.com/dwest1507/eliza-assessment/issues/125)
* **retrieval:** an outlook route to the latest MD&A ([379b10f](https://github.com/dwest1507/eliza-assessment/commit/379b10f331e112368f12b8d9b2534b25270103d4)), closes [#122](https://github.com/dwest1507/eliza-assessment/issues/122)
* **retrieval:** get the Required Facts' evidence into the Answer Context ([c055d9d](https://github.com/dwest1507/eliza-assessment/commit/c055d9d9372d4701755c9d2079e7a12e0b797d7b))
* **retrieval:** legal proceedings questions also search the Financial Statements ([e239de7](https://github.com/dwest1507/eliza-assessment/commit/e239de7e708219c1af040cfe6727b452392c65fd)), closes [#120](https://github.com/dwest1507/eliza-assessment/issues/120)
* **retrieval:** Market Risk phrasings and a cybersecurity route ([89ff5cc](https://github.com/dwest1507/eliza-assessment/commit/89ff5ccff9dd431c70bdee8e40894ce0b4696410)), closes [#119](https://github.com/dwest1507/eliza-assessment/issues/119)
* **retrieval:** one Evidence Reached function, and the searched Sections shown end to end ([271a2e8](https://github.com/dwest1507/eliza-assessment/commit/271a2e8345ab80ec490cb54cb92249e99068cc85)), closes [#117](https://github.com/dwest1507/eliza-assessment/issues/117)
* **retrieval:** response and dependence phrases add Business and MD&A ([59a8620](https://github.com/dwest1507/eliza-assessment/commit/59a8620105ea5f4f67249982a6c6d073af8fe27e)), closes [#121](https://github.com/dwest1507/eliza-assessment/issues/121)
* **retrieval:** search terms drop generic words and the words that set a Section hint ([a2697f5](https://github.com/dwest1507/eliza-assessment/commit/a2697f55973fa2628ee3d02b307c8a2b600b923d)), closes [#123](https://github.com/dwest1507/eliza-assessment/issues/123)
* **retrieval:** the context budget passes to Companies that can use it ([6f4a622](https://github.com/dwest1507/eliza-assessment/commit/6f4a6229d2fb002eb23abe6016875215746bebc1)), closes [#124](https://github.com/dwest1507/eliza-assessment/issues/124)

## [0.3.1](https://github.com/dwest1507/eliza-assessment/compare/eliza-assessment-v0.3.0...eliza-assessment-v0.3.1) (2026-10-18)


### Bug Fixes

* **eval:** fix version 2's measurement and re-baseline dev before the retrieval work ([bd1cf91](https://github.com/dwest1507/eliza-assessment/commit/bd1cf916bc151018ca0e643c26a65217f546ced1))
* **eval:** keep expected Coverage Gap sentences from Jev's Faithfulness judgment ([01641be](https://github.com/dwest1507/eliza-assessment/commit/01641be80e213cc99880ad6b7561f1829a4bf89f)), closes [#86](https://github.com/dwest1507/eliza-assessment/issues/86)
* **eval:** keep uncited refusals in no-Source answers out of Faithfulness ([139372d](https://github.com/dwest1507/eliza-assessment/commit/139372dbdf8013c3c5a73abd30e28c97e4463b53)), closes [#109](https://github.com/dwest1507/eliza-assessment/issues/109)
* **eval:** keep uncited sentences that name the records in passing as claims ([b7170cd](https://github.com/dwest1507/eliza-assessment/commit/b7170cd6b85d7309da77a7a267be08b8a9749601)), closes [#111](https://github.com/dwest1507/eliza-assessment/issues/111)
* **eval:** narrow Faithfulness's claim exemption to stated Coverage Gaps ([987bb7f](https://github.com/dwest1507/eliza-assessment/commit/987bb7f1d05e1704362d8625e6ae3e9e42a49949)), closes [#89](https://github.com/dwest1507/eliza-assessment/issues/89)
* **eval:** score a truncated answer's Fact Recall 0 when its judgment failed ([793430d](https://github.com/dwest1507/eliza-assessment/commit/793430de93b6171b542ee90f173c5adbb1dc3c6e)), closes [#90](https://github.com/dwest1507/eliza-assessment/issues/90)
* **eval:** state the default generator comparison once, in generators.py ([0545320](https://github.com/dwest1507/eliza-assessment/commit/0545320d21312a3d3ebce8b4d8bd6264d5890d08)), closes [#91](https://github.com/dwest1507/eliza-assessment/issues/91)

## [0.3.0](https://github.com/dwest1507/eliza-assessment/compare/eliza-assessment-v0.2.0...eliza-assessment-v0.3.0) (2026-10-18)


### Features

* **frontend:** a plain error with "Try again" when an answer can't load ([525c889](https://github.com/dwest1507/eliza-assessment/commit/525c889603af7f8441d3f1a7b5c6ca17d901d5b7)), closes [#99](https://github.com/dwest1507/eliza-assessment/issues/99)
* **frontend:** a simpler default workspace, with depth on demand ([b1c9a26](https://github.com/dwest1507/eliza-assessment/commit/b1c9a2684a2cf55428ffb68bc8b6036fde66f55d))
* **frontend:** a Sources panel a non-technical reader can follow ([1af65c8](https://github.com/dwest1507/eliza-assessment/commit/1af65c85086047c4b591907a5ed2859598c5c5c4)), closes [#98](https://github.com/dwest1507/eliza-assessment/issues/98)
* **frontend:** collapse "How it works" technical sections by default ([eb8975e](https://github.com/dwest1507/eliza-assessment/commit/eb8975eda029607180f286bee87eee1dd2096526)), closes [#102](https://github.com/dwest1507/eliza-assessment/issues/102)
* **frontend:** fit the coverage grid to the screen, with its header and Company columns fixed ([440b7a1](https://github.com/dwest1507/eliza-assessment/commit/440b7a1897747e5f4540cac7b4a5e64d5ec07699)), closes [#104](https://github.com/dwest1507/eliza-assessment/issues/104)
* **frontend:** keep the reader's place while an answer streams ([69118eb](https://github.com/dwest1507/eliza-assessment/commit/69118eb21227d9397f13e1be2a0bd3ee487d5db5)), closes [#95](https://github.com/dwest1507/eliza-assessment/issues/95)
* **frontend:** open "How it works" with a plain overview ([8ce53c7](https://github.com/dwest1507/eliza-assessment/commit/8ce53c75224df9df1d907b08499e512fba785ce3)), closes [#103](https://github.com/dwest1507/eliza-assessment/issues/103) [#94](https://github.com/dwest1507/eliza-assessment/issues/94)
* **frontend:** readable text and plain wording in the default view ([f5cf027](https://github.com/dwest1507/eliza-assessment/commit/f5cf027c242b8715b183c792e6394dc85dd582d2)), closes [#105](https://github.com/dwest1507/eliza-assessment/issues/105)
* **frontend:** show an answer's short answer first, with "Show full analysis" ([5b28104](https://github.com/dwest1507/eliza-assessment/commit/5b2810456a77fd294bedb41353e3b5b7e0b96c60)), closes [#97](https://github.com/dwest1507/eliza-assessment/issues/97)
* **frontend:** show an answer's Sources and Query Scope only once complete ([c991b36](https://github.com/dwest1507/eliza-assessment/commit/c991b36401598869f6f1331a79aef508dc7300ef)), closes [#96](https://github.com/dwest1507/eliza-assessment/issues/96)
* **frontend:** show what's covered on the empty workspace and "How it works" ([7fd7bee](https://github.com/dwest1507/eliza-assessment/commit/7fd7bee62f09c2b4fbf63149de1092a4d0002570)), closes [#100](https://github.com/dwest1507/eliza-assessment/issues/100)
* **frontend:** suggest follow-up questions from templates ([05913ea](https://github.com/dwest1507/eliza-assessment/commit/05913ea0ea0c01563cb45eedfaa209fd21fa477e)), closes [#101](https://github.com/dwest1507/eliza-assessment/issues/101) [#94](https://github.com/dwest1507/eliza-assessment/issues/94)


### Bug Fixes

* **frontend:** close the gaps the review found after the default-view tasks ([9d7cf78](https://github.com/dwest1507/eliza-assessment/commit/9d7cf781570deb58e23abe63f5c6fc25cb0587eb)), closes [#106](https://github.com/dwest1507/eliza-assessment/issues/106)

## [0.2.0](https://github.com/dwest1507/eliza-assessment/compare/eliza-assessment-v0.1.0...eliza-assessment-v0.2.0) (2026-10-17)


### Features

* **eval:** add Brief Suite variants of the brief's first two questions ([a78cab7](https://github.com/dwest1507/eliza-assessment/commit/a78cab7f535ce312d9e6fd6a48f124fe173b19cc)), closes [#48](https://github.com/dwest1507/eliza-assessment/issues/48)
* **eval:** add Brief Suite variants of the brief's pharmaceutical question ([5023383](https://github.com/dwest1507/eliza-assessment/commit/5023383ad63e7b06f82cef730ca4e4a29db0b440)), closes [#49](https://github.com/dwest1507/eliza-assessment/issues/49)
* **eval:** add claude-haiku-5-5 to the generators table ([8816675](https://github.com/dwest1507/eliza-assessment/commit/88166756472d2f64b9562a81b7f05f6f39a68b00)), closes [#54](https://github.com/dwest1507/eliza-assessment/issues/54)
* **eval:** add Golden Set v2's fifth slice of new cases, eight sector questions and a periods differ comparison ([881e6c1](https://github.com/dwest1507/eliza-assessment/commit/881e6c143d422ca35d88c248060f37c2fb23f890)), closes [#70](https://github.com/dwest1507/eliza-assessment/issues/70)
* **eval:** add Golden Set v2's first slice of new cases, nine risk comparisons ([a67592f](https://github.com/dwest1507/eliza-assessment/commit/a67592f60f2edb55ab608fcc2ec9fa85e8e74d63)), closes [#66](https://github.com/dwest1507/eliza-assessment/issues/66)
* **eval:** add Golden Set v2's fourth slice of new cases, four outlooks and five sector questions ([90f4cbe](https://github.com/dwest1507/eliza-assessment/commit/90f4cbe0186f243d24f461a39028c0e59d5ced6b)), closes [#69](https://github.com/dwest1507/eliza-assessment/issues/69)
* **eval:** add Golden Set v2's last slice of new cases, five Coverage Gap cases and three follow-ups ([062454a](https://github.com/dwest1507/eliza-assessment/commit/062454a84638d44a9ab741d7397fe75063a05bfc)), closes [#71](https://github.com/dwest1507/eliza-assessment/issues/71)
* **eval:** add Golden Set v2's second slice of new cases, seven risk questions and two follow-ups ([c0e5a18](https://github.com/dwest1507/eliza-assessment/commit/c0e5a189989b0b0f4451ad48655bdc2e00227d71)), closes [#67](https://github.com/dwest1507/eliza-assessment/issues/67)
* **eval:** add Golden Set v2's third slice of new cases, nine figure trends ([5bd8546](https://github.com/dwest1507/eliza-assessment/commit/5bd8546ae838be69a54311432aca888425889444)), closes [#68](https://github.com/dwest1507/eliza-assessment/issues/68)
* **eval:** add Golden Set version 2's file, a split recorded per case ([f7f90ce](https://github.com/dwest1507/eliza-assessment/commit/f7f90cea5d4c70c206f1eb8df512d875576b6a7b)), closes [#58](https://github.com/dwest1507/eliza-assessment/issues/58)
* **eval:** add Pfizer's September 2025 agreements to the pharmaceutical brief case ([ab44bff](https://github.com/dwest1507/eliza-assessment/commit/ab44bff3e0ab736e28211f953ceb3b3da1e22875)), closes [#43](https://github.com/dwest1507/eliza-assessment/issues/43)
* **eval:** add the Brief Suite, run 5 times a case with a verdict per case ([9820a70](https://github.com/dwest1507/eliza-assessment/commit/9820a70155e054a3b65fa14670995debf901ded8)), closes [#47](https://github.com/dwest1507/eliza-assessment/issues/47) [#43](https://github.com/dwest1507/eliza-assessment/issues/43)
* **eval:** build and run evaluation version 2: the Brief Suite, Golden Set v2 and a judge study ([b09c4e6](https://github.com/dwest1507/eliza-assessment/commit/b09c4e646bd535d0c5be584e8b8332728bc49608))
* **eval:** compare gpt-6-luna with claude-haiku-5-5 by default ([1cb603e](https://github.com/dwest1507/eliza-assessment/commit/1cb603ee1c3128333e116d0f68a33fde8327270c)), closes [#54](https://github.com/dwest1507/eliza-assessment/issues/54)
* **eval:** each claim reaches the judge with its heading and table header ([279bb6a](https://github.com/dwest1507/eliza-assessment/commit/279bb6ab40d95da95c5b50062393eafa82975944)), closes [#53](https://github.com/dwest1507/eliza-assessment/issues/53)
* **eval:** every comparison has a Control Run, one per round ([21bfc84](https://github.com/dwest1507/eliza-assessment/commit/21bfc8423bbf462edde638ae9672b1304a5990b4)), closes [#56](https://github.com/dwest1507/eliza-assessment/issues/56)
* **eval:** fail an answer with a Contradicted Claim and count them per answer ([6d5a9fa](https://github.com/dwest1507/eliza-assessment/commit/6d5a9fa3a389e31dccd3f9474563175bd8632eec)), closes [#46](https://github.com/dwest1507/eliza-assessment/issues/46) [#43](https://github.com/dwest1507/eliza-assessment/issues/43)
* **eval:** Faithfulness covers every sentence; an uncited claim is unsupported ([2d7fa3a](https://github.com/dwest1507/eliza-assessment/commit/2d7fa3a51187274c0a16881156e0d7819cf736ed)), closes [#52](https://github.com/dwest1507/eliza-assessment/issues/52)
* **eval:** freeze Golden Set v2's split and make it the harnesses' default ([1f4f3fc](https://github.com/dwest1507/eliza-assessment/commit/1f4f3fc69797d306b0bd95a71aee69026249a00d)), closes [#72](https://github.com/dwest1507/eliza-assessment/issues/72)
* **eval:** gate retrieval on Evidence Reached and screen candidates before paid runs ([1fc379c](https://github.com/dwest1507/eliza-assessment/commit/1fc379c048aa86d8c68cb51296c74a7698b21f4d)), closes [#57](https://github.com/dwest1507/eliza-assessment/issues/57)
* **eval:** judge study sample and blind labelling sheet ([c764f01](https://github.com/dwest1507/eliza-assessment/commit/c764f010fd45e04e7d7a5e5ec3da18527ac0cfa0)), closes [#62](https://github.com/dwest1507/eliza-assessment/issues/62)
* **eval:** judge the study's items twice and score Jev against the labels ([e7b2c43](https://github.com/dwest1507/eliza-assessment/commit/e7b2c43f79e9c2a60190b3d6ac0ee203308689c6)), closes [#63](https://github.com/dwest1507/eliza-assessment/issues/63)
* **eval:** keep the judge study's sheet and sample under version control ([f6bb5e5](https://github.com/dwest1507/eliza-assessment/commit/f6bb5e5e8f4184529aa05b85ced5ee5460794df9)), closes [#43](https://github.com/dwest1507/eliza-assessment/issues/43)
* **eval:** local embedding Arms, and only Arms with no query-time API call can ship ([0d2b775](https://github.com/dwest1507/eliza-assessment/commit/0d2b7751c9de58e82d77eeb1034a473e15afc361)), closes [#84](https://github.com/dwest1507/eliza-assessment/issues/84)
* **eval:** move the "How it works" page and its export to Golden Set version 2 ([f1cade5](https://github.com/dwest1507/eliza-assessment/commit/f1cade58acd0e22824785103d5682f60da34adcc)), closes [#85](https://github.com/dwest1507/eliza-assessment/issues/85)
* **eval:** one-sided thresholds for every selection rule, with a bootstrap interval ([489dd0b](https://github.com/dwest1507/eliza-assessment/commit/489dd0bec49be56720acbf67017c7f4dffc874fb)), closes [#55](https://github.com/dwest1507/eliza-assessment/issues/55)
* **eval:** record a Jev failure against its judgment, not the whole case ([f0d8c61](https://github.com/dwest1507/eliza-assessment/commit/f0d8c61a2e05eb6acce1c3b83e778332ebbc7c4b)), closes [#50](https://github.com/dwest1507/eliza-assessment/issues/50) [#43](https://github.com/dwest1507/eliza-assessment/issues/43)
* **eval:** record the judge study's outcome and set the fact cut-off to 0.6 ([2018bdb](https://github.com/dwest1507/eliza-assessment/commit/2018bdb6c120e4981b239e5049055dee2e408f47)), closes [#65](https://github.com/dwest1507/eliza-assessment/issues/65)
* **eval:** record why the model stopped; fail answers cut off at the token cap ([18e9540](https://github.com/dwest1507/eliza-assessment/commit/18e9540b0bdc5183aa41a76c13f91dff76bac469)), closes [#51](https://github.com/dwest1507/eliza-assessment/issues/51)
* **eval:** rewrite nine version 1 figure, outlook and GE cases into Golden Set v2 ([c5852ac](https://github.com/dwest1507/eliza-assessment/commit/c5852ac6548c0988723c02872663fa924029b2a4)), closes [#60](https://github.com/dwest1507/eliza-assessment/issues/60)
* **eval:** rewrite nine version 1 risk, sector and Wells Fargo cases into Golden Set v2 ([3701487](https://github.com/dwest1507/eliza-assessment/commit/3701487ce3526c843ae08046d751bc7159bb237c)), closes [#59](https://github.com/dwest1507/eliza-assessment/issues/59)
* **eval:** rewrite the last nine version 1 cases into Golden Set v2 ([07e7a9b](https://github.com/dwest1507/eliza-assessment/commit/07e7a9b0b5ed5ad6c06f19c9378e983ff452dc3e)), closes [#61](https://github.com/dwest1507/eliza-assessment/issues/61)
* **eval:** tier Required Facts must-state or detail ([c044c9c](https://github.com/dwest1507/eliza-assessment/commit/c044c9cd8149568bf62d0fb8b245e5512ca9dc68)), closes [#45](https://github.com/dwest1507/eliza-assessment/issues/45)
* **eval:** trial LLM claim split in the judge study, compared with the sentence split ([9992018](https://github.com/dwest1507/eliza-assessment/commit/9992018cd0411c922ec972e14a02f3bf643f6ca6)), closes [#64](https://github.com/dwest1507/eliza-assessment/issues/64)


### Bug Fixes

* **eval:** don't end a claim after "U.S." or a common abbreviation ([5b4c50b](https://github.com/dwest1507/eliza-assessment/commit/5b4c50b559ca190ead98c95e58ebbd2394c5ee86)), closes [#83](https://github.com/dwest1507/eliza-assessment/issues/83)
* **security:** accept only Source tags as keys of the history's cited Filings ([6d95872](https://github.com/dwest1507/eliza-assessment/commit/6d95872d39316cb13fcd1d12c796b9579312bec6))
