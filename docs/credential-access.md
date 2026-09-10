# Credential access during development

Use the existing ignored project `.env` for application configuration. Do not paste keys into chat. `.gitignore` prevents ordinary Git tracking; it does not prevent an agent with filesystem access from reading a file. The project `AGENTS.md` prohibits inspecting or exposing secrets, but instructions alone are not an OS access boundary.

Codex 0.154.0 supports named permission profiles with filesystem `deny` rules. A local `env-guard` profile has been prepared in the user's Codex configuration. It denies the exact project `.env` and `.env` files under workspace roots, with nested glob scanning limited to eight levels. It has **not** been made the default: on this host, sandbox startup currently fails while setting up a Linux user namespace (`uid map: Permission denied`). The current task still has unrestricted filesystem access. No real credential file was read in the deny-rule test; it used a newly created synthetic fixture.

After the host sandbox is repaired, test with a harmless fixture before selecting `env-guard` in Codex's permission controls. Full-access sessions do not enforce this profile. A lasting administrative policy must also prevent selecting a profile that bypasses it. The application needs to be launched separately by the user if Codex's sandbox is forbidden from reading its configuration file.

For a stronger separation of the actual API credential, run the credential-bearing application under a separate OS identity or use a restricted credential service. An agent that can change and run credential-bearing application code must not be assumed unable to obtain its credentials solely because the filename is denied.

Official references: [Codex permission profiles](https://learn.chatgpt.com/docs/permissions), [configuration and managed requirements](https://learn.chatgpt.com/docs/config-file/config-reference).
