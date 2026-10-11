"""A profile switch cannot expose the previous process's loaded business data."""
import asyncio

import httpx

from clipbot.auth import COOKIE, ProfileStore
from clipbot.dashboard.server import create_app
from tests.test_account_profiles import context

H = {"X-ClipBot": "1"}


def test_first_setup_and_profile_switch_hold_both_users_until_new_runtime(tmp_path):
    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, service = context(tmp_path / "owner-one", engine)
            restart_requests = []
            ctx.request_quit = lambda restart=False: restart_requests.append(restart)
            app = create_app(ctx)
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as owner:
                assert (await owner.get("/api/account-profiles/clips")).status_code == 401
                setup = await owner.post("/api/auth/setup", headers=H, json={"name": "First", "password": "first-password"})
                assert setup.status_code == 200
                original_cookie = owner.cookies.get(COOKIE)
                first_id = setup.json()["profile"]["id"]
                assert (await owner.get("/api/auth/status")).json()["signed_in"] is True
                assert (await owner.get("/api/account-profiles/clips")).status_code == 200
                second = await owner.post("/api/profiles", headers=H, json={"name": "Second", "password": "second-password"})
                second_id = second.json()["profile"]["id"]
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as other:
                    login = await other.post("/api/auth/login", headers=H, json={"profile_id": second_id, "password": "second-password", "device": "phone"})
                    assert login.status_code == 200 and login.json()["restarting"] is True
                    token = login.json()["token"]
                    await asyncio.sleep(0)
                    assert restart_requests == [True]
                    assert ProfileStore().last() == second_id
                    assert (await other.get("/api/auth/status")).json()["signed_in"] is False
                    assert (await other.get("/api/auth/status")).json()["restarting"] is True
                    for client in (owner, other):
                        denied = await client.get("/api/account-profiles/clips")
                        assert denied.status_code == 401 and denied.json()["restarting"] is True
                        assert "default-secret" not in denied.text
                        assert (await client.post("/api/settings/reset/accounts", headers=H)).status_code == 401
                    # A newly constructed runtime belongs to the selected user's data.
                    new_ctx, new_service = context(tmp_path / "owner-two", engine)
                    new_app = create_app(new_ctx)
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=new_app), base_url="http://127.0.0.1:8787") as restarted:
                        accepted = await restarted.get("/api/account-profiles/clips", headers={"Authorization": f"Bearer {token}"})
                        assert accepted.status_code == 200
                        restarted.cookies.set(COOKIE, original_cookie)
                        old = await restarted.get("/api/account-profiles/clips")
                        assert old.status_code == 401
                        assert (await restarted.get("/api/auth/status", headers={"Authorization": f"Bearer {token}"})).json()["signed_in"] is True
                assert first_id != second_id
    asyncio.run(run())


def test_profile_login_waits_for_in_progress_settings_save(tmp_path):
    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, service = context(tmp_path, engine)
            ctx.request_quit = lambda restart=False: None
            app = create_app(ctx)
            entered, finish = asyncio.Event(), asyncio.Event()
            original_commit = ctx.commit_settings
            writes = []
            async def slow_commit(settings):
                entered.set()
                await finish.wait()
                writes.append(ProfileStore().last())
                return await original_commit(settings)
            ctx.commit_settings = slow_commit
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as owner:
                setup = await owner.post("/api/auth/setup", headers=H, json={"name": "First", "password": "first-password"})
                first_id = setup.json()["profile"]["id"]
                second = await owner.post("/api/profiles", headers=H, json={"name": "Second", "password": "second-password"})
                second_id = second.json()["profile"]["id"]
                save = asyncio.create_task(owner.put("/api/settings", headers=H, json={"settings": {"brand": {"name": "Saved for first owner"}}}))
                await entered.wait()
                async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8787") as other:
                    body = {"profile_id": second_id, "password": "second-password"}
                    denied = await other.post("/api/auth/login", headers=H, json=body)
                    assert denied.status_code == 409
                    assert ProfileStore().last() == first_id
                    assert not (await owner.get("/api/auth/status")).json()["restarting"]
                    finish.set()
                    saved = await save
                    assert saved.status_code == 200, saved.text
                    assert writes == [first_id]
                    accepted = await other.post("/api/auth/login", headers=H, json=body)
                    assert accepted.status_code == 200 and accepted.json()["restarting"]
    asyncio.run(run())


def test_bearer_logout_revokes_phone_session_and_password_change_revokes_browser(tmp_path):
    async def run():
        async with httpx.AsyncClient() as engine:
            ctx, service = context(tmp_path, engine)
            app = create_app(ctx)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787") as client:
                setup = await client.post("/api/auth/setup", headers=H, json={"name": "Owner", "password": "first-password"})
                identity = setup.json()["profile"]["id"]
                login = await client.post("/api/auth/login", headers=H, json={"profile_id": identity, "password": "first-password", "device": "phone"})
                token = login.json()["token"]
                phone_headers = H | {"Authorization": f"Bearer {token}"}
                assert (await client.get("/api/account-profiles/clips", headers=phone_headers)).status_code == 200
                assert (await client.post("/api/auth/logout", headers=phone_headers)).status_code == 200
                assert (await client.get("/api/account-profiles/clips", headers=phone_headers)).status_code == 401
                login = await client.post("/api/auth/login", headers=H, json={"profile_id": identity, "password": "first-password"})
                assert login.status_code == 200 and not login.json()["restarting"]
                changed = await client.post("/api/profiles/password", headers=H, json={"old": "first-password", "new": "new-owner-password"})
                assert changed.status_code == 200
                assert (await client.get("/api/account-profiles/clips")).status_code == 401
                assert (await client.get("/api/auth/status")).json()["signed_in"] is False
                assert (await client.post("/api/auth/login", headers=H, json={"profile_id": identity, "password": "new-owner-password"})).status_code == 200
    asyncio.run(run())
