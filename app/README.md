# TI Agent app (Flutter)

A mobile/desktop/web client for TI Agent. You sign in, then scroll through this week's suggestions:
- **Opening screen:** fades away as you scroll.
- **At a glance:** a grid of every ticker's two views.
- **One scene per ticker:** the symbol grows into place, and the 1–3 month and 6–24 month views slide in
  from the left and right as you scroll.
- **Contact:** LinkedIn and GitHub.

Tap a source chip to read the exact passage a suggestion cites. Tap **Chart and history** for a
12-month chart against the benchmark.

It follows the same rules as the website: invite-only, read-only, no financial advice.

> **Status:** written but **not yet compiled**. The Flutter SDK wasn't installed on the machine it was
> written on. Expect to fix a few small compile issues on the first `flutter analyze`.

## How it reads data

There is no server of its own. The app talks to Supabase directly with the **public anon key** and
**Supabase Auth**, so row-level security in [db/rls.sql](../db/rls.sql) decides what it can see:

| Data | Access |
|---|---|
| `suggestions`, `tickers`, `prices` | Read, for signed-in users |
| `agent_runs` | Read: `id, as_of, status, model, started_at, finished_at` only (not `error`) |
| Cited passages | Through `app_citations(ids)`: only chunks some suggestion cites, at most 20 per call |
| Raw documents, chunks, logs, any writes | No access |

**The app refuses to start with a service or secret key.** Anything inside an app can be extracted from
it, and those keys bypass row-level security.

## Setup

1. **Database.** Re-run [db/rls.sql](../db/rls.sql) in the Supabase SQL editor. It is safe to run again,
   and it adds the app's read access.
2. **Turn off public sign-ups.** In Supabase, go to *Authentication → Sign In / Providers* and turn off
   *Allow new users to sign up*. Create accounts in *Authentication → Users → Add user* (tick *Auto
   confirm*). Without this step, anyone could create an account and read results.
3. **Install Flutter** (stable): <https://docs.flutter.dev/get-started/install/windows>. Then run
   `flutter doctor`.
4. **Generate the platform folders.** This repo holds only the Dart code. Existing files are not
   overwritten:
   ```powershell
   cd app
   flutter create --project-name ti_agent --platforms=android,ios,web,windows .
   flutter pub get
   ```
5. **Configure.** Copy `config.example.json` to `config.json` (it's ignored by git) and fill in:
   - `SUPABASE_URL`
   - `SUPABASE_ANON_KEY`: *Project Settings → API keys*, the **anon / publishable** key
   - `LINKEDIN_URL`: optional

## Run and test

```powershell
flutter analyze
flutter test
flutter run -d chrome  --dart-define-from-file=config.json   # or -d edge, -d windows, an Android device
```

For a release build, add `--dart-define-from-file=config.json` to `flutter build apk` / `ipa` / `web`.

## Layout

| File | What it does |
|---|---|
| `lib/main.dart` | Checks the configuration, starts Supabase, and switches between login and home |
| `lib/config.dart` | Build-time settings and the service-key check |
| `lib/models.dart` | Run, suggestion, citation and price rows; the http(s)-only link filter |
| `lib/data.dart` | The `DataSource` interface, its Supabase implementation, and the home-page logic (grouping, new/changed, stats) |
| `lib/widgets/scroll_scrub.dart` | Turns a widget's position on screen into a 0→1 progress value, which drives the scroll animations |
| `lib/screens/` | Login, home (scroll story), ticker detail (chart and history) |
| `test/` | Logic and widget tests against an in-memory fake (no network) |

Accessibility: with the system *reduce motion* setting on, nothing animates and everything is shown.
Stance always comes with a shape (▲ ■ ▼) and a word, never colour alone.
