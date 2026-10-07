# How we cut onboarding from nine days to two

Last March our median new-hire onboarding took nine working days. We measured it from offer acceptance to first merged pull request. Today it takes two.

Three changes did most of the work.

We pre-provisioned laptops. IT used to wait for the start date, which burned three days on shipping and setup. Now the laptop ships the week the offer is signed.

We replaced the 40-page setup doc with a single script. The script installs the toolchain, clones the four repos a new engineer needs, and seeds a local database. It runs in about eleven minutes.

We gave every new engineer a scoped first ticket before day one. Their manager picks something small and real from the backlog. Six of the last eight hires merged that ticket on day two.

The remaining friction is access reviews. Security signs off on production credentials manually, and that queue still averages a day and a half. We are working on it.
