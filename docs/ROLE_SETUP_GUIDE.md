# Administrator, Dungeon Master, and Player Setup Guide

This guide explains how to prepare a fresh TableTop DM installation and how to configure each
human-facing role through the browser. It is intentionally separate from the project README so it
can be handed directly to the person administering or joining a game.

## Role model at a glance

TableTop DM uses three product roles:

| Role | Scope | What it unlocks |
| --- | --- | --- |
| `ADMIN` | Entire installation | Account management and every simulation/operations workspace |
| `DM` | One world at a time | Dungeon Master tools and game hosting for that world |
| `PLAYER` | One world at a time | Player tools, characters, and participation in that world |

An account can hold both `DM` and `PLAYER`. This is the supported **Player DM** configuration: the
same person can host games and maintain their own player characters. World roles do not carry into
another world automatically.

## Before anyone signs in

1. Start the durable application from the repository root:

   ```powershell
   uv run python scripts/manage.py start
   uv run python scripts/manage.py status
   ```

2. Wait until the application, worker, projector, PostgreSQL, Redis, and Qdrant report healthy.
3. Open [http://127.0.0.1:8000/v2](http://127.0.0.1:8000/v2).
4. Do not share the generated `.env` file or `TTDM_OPERATOR_TOKEN`. Browser users sign in with
   their own accounts; the operator token is for local automation only.

To stop the application without deleting saved data:

```powershell
uv run python scripts/manage.py stop
```

## Part 1: Set up the first administrator

### 1. Sign in with the installation account

On a fresh installation, use:

- **Username:** `admin`
- **Password:** `admin123`

These are bootstrap credentials, not a permanent password. The default account cannot enter the
protected application until its password is changed.

### 2. Complete the required password change

The first sign-in opens **Protect the administrator account**.

1. Enter `admin123` in **Current password**.
2. Enter a private password in **New password**.
3. Enter it again in **Confirm new password**.
4. Select **Change password and continue**.

The replacement must contain at least 12 characters and cannot be a common default password. Store
it in a password manager. Changing the password rotates the session and prevents continued use of
the shared bootstrap password.

### 3. Complete the administrator profile

1. Open **Settings**.
2. Under **Personal information**, enter the desired display name and any optional legal name,
   email, date of birth, pronouns, timezone, locale, and biography.
3. Select **Save profile**.

Every account can maintain these settings. Usernames are changed by an administrator rather than
from the personal profile form.

### 4. Confirm or create the game world

DM and Player roles are assigned to a specific world, so a world must exist before those roles can
be granted.

1. Open **Control Plane**.
2. Check the **Worlds** section for the world that will contain the campaign.
3. If necessary, use the world creation controls to create it.
4. Select the intended world in the application world selector before continuing.

The administrator may use Control Plane for low-level world, actor, entity, run, snapshot, and
branch management. Regular game hosting belongs in the Dungeon Master workspace.

### 5. Create a user account

1. Open **Admin Dashboard**.
2. Select **Add account**.
3. Enter the user's **Display name**.
4. Enter a unique **Username** of at least three characters.
5. Enter a **Temporary password** of at least 12 characters.
6. Select **Create account**.
7. Give the username and temporary password to that user through a private channel.

The user will be forced to replace the temporary password at first sign-in, just like the bootstrap
administrator.

### 6. Assign account access and roles

1. In **Admin Dashboard**, select the account from **Accounts**.
2. Leave **Account enabled** selected unless access should be suspended.
3. Select **Administrator** only if this person must administer the entire installation.
4. Under **World roles**, select the correct **World**.
5. Choose one or both of the following:
   - **Dungeon Master** — host games and manage rosters and sessions in this world.
   - **Player** — create characters and join games in this world.
6. Select **Save world roles**.

For a Player DM, select both **Dungeon Master** and **Player**, then save. Repeat the world-role
steps for each additional world the account should access.

### 7. Maintain existing accounts

The selected account's editor also allows an administrator to:

- enable or disable sign-in;
- grant or revoke global Administrator access;
- change world-scoped DM and Player roles;
- reset the account to a new temporary password;
- delete the login while preserving authored simulation history.

A password reset signs out the user's existing sessions and requires another password change at
the next sign-in. The application prevents disabling, deleting, or removing the role from the last
usable administrator.

## Part 2: Set up and operate as a Dungeon Master

### Administrator prerequisite

Before the DM signs in, an administrator must:

1. create the DM's account;
2. select the campaign world in that account's **World roles**;
3. select **Dungeon Master**;
4. select **Save world roles**.

Select both Dungeon Master and Player if the DM will also play a character.

### 1. Complete first sign-in

1. Open [http://127.0.0.1:8000/v2](http://127.0.0.1:8000/v2).
2. Sign in with the username and temporary password supplied by the administrator.
3. Replace that temporary password when prompted. The new password must contain at least 12
   characters.
4. Open **Settings**, complete the profile, and select **Save profile**.

### 2. Host a game

1. Select the intended world in the application world selector.
2. Open **Dungeon Master**.
3. Select **Host a game**.
4. Select the **World**.
5. Enter a **Game name** and optional **Description**.
6. Select **Create game**.

The game now appears under **Hosted games**. Select it to open its live-table controls.

### 3. Add players or a co-DM

The administrator must first give each participant the matching role in the same world:

- a normal participant needs `PLAYER`;
- a co-DM needs `DM`;
- a person who does both needs both roles.

Then:

1. Open the hosted game.
2. Under **Players in game**, choose an eligible account.
3. Select **Invite**.
4. Confirm the new roster entry and its status.

A player's saved character can be bound to their membership. Once bound, the player receives
permission to act through that specific embodied character—not administrative control over other
entities in the world.

### 4. Schedule and run sessions

1. Under **Sessions**, enter a **Session title**.
2. Select **Add session**.
3. Select **Start** on a session when play begins.
4. Select **Complete** when that session ends.

Use the game-level controls to:

- **Start game** — set the hosted game to live;
- **Pause** — pause the hosted game status;
- **Complete** — mark the hosted game complete.

These game/session status controls are different from simulation time controls. A visual or
tactical camera does not freeze the world; use an explicit hard-pause mechanism when one is
available for the active game mode.

### 5. Use DM visibility responsibly

DM tools can inspect canonical state and hidden information that players cannot see. Player-facing
views remain perception scoped: a player's map and observation feed reveal only what their selected
character could perceive. When validating split-party play, use a player's embodied viewpoint
rather than assuming the canonical DM view matches the player's knowledge.

## Part 3: Set up and operate as a Player

### Administrator prerequisite

Before the player signs in, an administrator must:

1. create the player's account;
2. select the campaign world in that account's **World roles**;
3. select **Player**;
4. select **Save world roles**.

The DM can invite the player only to games in worlds where this role exists.

### 1. Complete first sign-in

1. Open [http://127.0.0.1:8000/v2](http://127.0.0.1:8000/v2).
2. Sign in with the username and temporary password supplied by the administrator.
3. Replace the temporary password when prompted.
4. Open **Settings**, complete the profile, and select **Save profile**.

### 2. Create a character

Open **Player Dashboard** and choose one of three methods:

#### Build a character

1. Select **Build character**.
2. Enter the character's identity and game fields.
3. Review the six ability scores.
4. Select **Save character**.

#### Generate a character

1. Select **Generate**.
2. Enter or retain the **Generation seed**.
3. Select **Generate and save**.

The same seed produces a reproducible starting character that can be edited afterward.

#### Import a character template

1. Select **Import**.
2. Choose a JSON character template smaller than 1 MB.
3. Select **Import and save**.

The imported data is validated before the character is saved.

### 3. Review character state

Under **Saved characters**, select a character to inspect:

- level, species, class, and background;
- current and maximum hit points;
- armor class and movement speed;
- Strength, Dexterity, Constitution, Intelligence, Wisdom, and Charisma;
- current status such as `ALIVE`, `DEAD`, `MISSING`, or `RETIRED`.

Use **Save status** after changing the editable status or hit-point fields. Deleting a character is
permanent and requires browser confirmation.

### 4. Join and play a hosted game

1. Ask the DM to invite the account to the hosted game and assign the intended saved character.
2. Check **My games** in Player Dashboard for the game and its current status.
3. Open **Game Console** after the character has been bound to an embodied entity.
4. Select the authorized character viewpoint.
5. Use normal prose for in-world speech and slash commands for typed actions such as movement.

The player cannot select or act through another player's character or a DM-controlled NPC. The map
and event feed are also knowledge scoped: entering a room later does not reveal conversations that
happened before the character arrived.

## Settings available to every account

Every signed-in account can open **Settings** to manage:

- display name, legal name, email, date of birth, and pronouns;
- timezone, locale, and biography;
- current password and a new password;
- sign-out and current role summary.

Changing a password requires the current password, a replacement of at least 12 characters, and
matching confirmation. It signs out the account's other sessions.

## Troubleshooting

### A workspace tab is missing

- Confirm the account is enabled.
- In Admin Dashboard, select the exact world and verify the appropriate DM or Player role.
- Select **Save world roles** after changing the checkboxes.
- Sign out and sign in again if the browser session predates the role change.

### A DM cannot see a player in the eligible-user list

Confirm the player has `PLAYER` in the hosted game's world. A role in a different world does not
qualify. A co-DM must have `DM` in that world.

### A player cannot act through a character

Creating a portal character is not, by itself, embodiment. Confirm the DM assigned that character
to the player's game membership so the character is linked to a kernel entity and the account has
control of that body.

### A user forgot their password

An administrator can select the account in **Admin Dashboard**, enter a new temporary password
under **Password reset**, and select **Reset**. All existing sessions are closed, and the user must
replace the temporary password at the next sign-in.

### An account is temporarily locked

Five failed sign-in attempts lock the account for 15 minutes. Further attempts during the lock do
not extend it. Wait for the lock to expire or use another administrator account to manage the user.

### The application does not load

From the repository root, run:

```powershell
uv run python scripts/manage.py status
```

Then check [http://127.0.0.1:8000/healthz](http://127.0.0.1:8000/healthz) and
[http://127.0.0.1:8000/readyz](http://127.0.0.1:8000/readyz). The readiness response identifies a
database, queue, vector-store, or migration dependency that is not ready.

## Setup checklists

### Administrator

- [ ] Changed the bootstrap `admin123` password.
- [ ] Completed the administrator profile.
- [ ] Confirmed or created the campaign world.
- [ ] Created individual user accounts with private temporary passwords.
- [ ] Assigned DM and Player roles in the correct world.
- [ ] Kept at least one usable Administrator account.

### Dungeon Master

- [ ] Replaced the temporary password and completed the profile.
- [ ] Confirmed the correct world is selected.
- [ ] Created a hosted game.
- [ ] Invited eligible players/co-DMs.
- [ ] Added the first session and reviewed game status controls.

### Player

- [ ] Replaced the temporary password and completed the profile.
- [ ] Created, generated, or imported a character.
- [ ] Confirmed the DM added the account to the game.
- [ ] Confirmed the character is bound before using Game Console.
- [ ] Reviewed character statistics and current game status.
