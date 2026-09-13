# Synthetic business applications

These applications provide controlled environments for exercising Enterprise Agent System. They contain synthetic records and have no real business accounts.

| Application | Purpose |
| --- | --- |
| `demobooks/` | Independent .NET Windows accounting desktop. Used to test accessibility and input automation with its application API disabled. |
| `campaign-desk/` | Independent read-only Python campaign metrics API for the Ubuntu Marketing worker. No real publishing, advertising accounts or mailer. |
| `ledger-fixture/` | Optional browser accounting fixture for automated tests without a Windows machine. Installed only with development dependencies. |

The server and harness install independently of these applications. Campaign Desk's outer directory is its project; `campaign_desk/` inside it is the Python import package. Generated `*.egg-info` is ignored by Git.
