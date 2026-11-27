# Section H hosted test results

The tested PR revision was `c47eddb87f6201d611183d96111a7ef56c7e74dd`. GitHub merged that exact
tree to `main` at `66df949d9cc5bb723bbc307f782ebdc979e41dc7`. [Pull request](https://github.com/SweetingTech/TableTop_DM/pull/135)

- The PostgreSQL integration job ran all 201 selected cases successfully. The party, autonomous
  invitation, coordination, and quest-transfer cases passed. These cases verify restart, normal
  death saves, one funded payout, and replay. [Integration job](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262738/job/140735504468)
- Chromium passed all 50 journeys. The two quest cases completed a main or alternate approach,
  read its progress, and claimed the reward. The alternate-route case showed the required item
  in both the offer and the personal journal. [Browser job](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262708/job/140735504036)
- The quality and image jobs passed. The independent GitHub review reports zero unresolved
  findings for the tested revision. [Quality and image](https://github.com/SweetingTech/TableTop_DM/actions/runs/46067262738) · [Review receipt](https://github.com/SweetingTech/TableTop_DM/pull/135#issuecomment-7226988620)

The [criterion map](acceptance.md) identifies the runnable source for each of the five Orderly
criteria and the shared resident journey.
