"""F1.6 — yerel (Türkiye IP'li bilgisayar) koşusu, Actions'ın atlaması ve dal/push yarışı."""

import json
import subprocess

import fiyat_kontrol as fk
import pytest
from helpers import (
    EXXEN_URL,
    REPO,
    SPOTIFY_URL,
    TURKCELL_URL,
    FakeGemini,
    FakeGit,
    FakeGitHub,
    answer,
    catalog,
    default_answers,
    make_root,
    pages,
    published_catalog,
    run,
)

LOCAL = frozenset({SPOTIFY_URL})


def spotify_hike():
    return {
        SPOTIFY_URL: [
            answer("spotify/bireysel", 129, "sonra ayda ₺129", True),
            answer("spotify/aile", 199, "Sonra ayda ₺199", False),
        ]
    }


def read(root, name):
    return json.loads((root / "durum" / name).read_text(encoding="utf-8"))


# --- Actions modu yerel kaynakları atlar ---


def test_actions_skips_local_sources_and_cleans_old_counters(tmp_path):
    root = make_root(tmp_path)
    durum = root / "durum"
    durum.mkdir()
    (durum / "okuma-hatalari.json").write_text(
        fk.dump_json(
            {
                "kaynaklar": {
                    SPOTIFY_URL: {"ardisik": 2, "ilk_hata": "x", "son_hata": "x", "neden": "TL yok"}
                },
                "planlar": {"spotify/aile": {"ardisik": 1, "ilk_hata": "x", "son_hata": "x", "neden": "?"}},
            }
        ),
        encoding="utf-8",
    )
    (durum / "sayfa-ozetleri.json").write_text(
        fk.dump_json({SPOTIFY_URL: {"karma": "eski", "degisim_tarihi": "x"}}), encoding="utf-8"
    )
    page_map = pages()
    del page_map[SPOTIFY_URL]  # indirilmeye çalışılsaydı "okunamadı" olurdu
    gemini = FakeGemini(default_answers())
    summary, gh, git = run(root, gemini=gemini, page_map=page_map, local_urls=LOCAL)

    assert SPOTIFY_URL not in gemini.calls
    # Turkcell örneği 'unconfirmed' kalır ve bir kez yeniden sorulur.
    assert sorted(gemini.calls) == sorted([EXXEN_URL, TURKCELL_URL, TURKCELL_URL])
    spotify = next(k for k in summary["kaynaklar"] if k["url"] == SPOTIFY_URL)
    assert spotify["durum"] == fk.LOCAL_STATUS
    assert summary["hata"] == 0 and gh.created_issues == []
    errors = read(root, "okuma-hatalari.json")
    assert errors["kaynaklar"] == {}
    assert not any(k.startswith("spotify/") for k in errors["planlar"])
    assert SPOTIFY_URL not in read(root, "sayfa-ozetleri.json")
    assert fk.LOCAL_STATUS in fk.render_summary(summary)
    assert not (durum / "yerel-okuma-hatalari.json").exists()


def test_actions_weekly_lists_local_sources_and_heartbeat(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub()
    summary, gh, git = run(root, gemini=FakeGemini(default_answers()), gh=gh, weekly=True, local_urls=LOCAL)
    body = next(b for t, b in gh.created_issues if t.startswith("İzlenemiyor"))
    assert "Yerelden izlenenler" in body and "`spotify/bireysel`" in body
    assert "hbo-max/standart" in body
    heartbeat = read(root, "son-calisma.json")
    assert heartbeat["toplam_kaynak"] == 2 and heartbeat["kontrol_edilen_kaynak"] == 2


STALE_TITLE = "Otomasyon: yerel fiyat kontrolü çalışmıyor"


@pytest.mark.parametrize(
    ("last", "expect_issue"),
    [("2026-11-16", False), ("2026-11-14", True)],
)
def test_every_actions_run_warns_when_local_run_is_stale(tmp_path, last, expect_issue):
    root = make_root(tmp_path)
    (root / "durum").mkdir()
    (root / "durum" / "yerel-son-calisma.json").write_text(fk.dump_json({"tarih": last}), encoding="utf-8")
    _, gh, _ = run(root, gemini=FakeGemini(default_answers()), local_urls=LOCAL)  # haftalık değil
    titles = [t for t, _ in gh.created_issues]
    assert (STALE_TITLE in titles) is expect_issue


def test_missing_local_heartbeat_is_remembered_then_warned_once(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub()
    for day, expect in [("2026-11-14", 0), ("2026-11-16", 0), ("2026-11-17", 1), ("2026-11-18", 1)]:
        run(root, day=day, gemini=FakeGemini(default_answers()), local_urls=LOCAL, gh=gh)
        assert read(root, "okuma-hatalari.json")["yerel_kosu_yok"] == {"ilk_fark": "2026-11-14"}
        assert [t for t, _ in gh.created_issues].count(STALE_TITLE) == expect  # açık issue tekrarlanmaz
    assert "hiç çalışmadı" in next(b for t, b in gh.created_issues if t == STALE_TITLE)
    # Yerel koşu başlayınca kayıt silinir.
    (root / "durum" / "yerel-son-calisma.json").write_text(
        fk.dump_json({"tarih": "2026-11-18"}), encoding="utf-8"
    )
    run(root, day="2026-11-18", gemini=FakeGemini(default_answers()), local_urls=LOCAL, gh=gh)
    assert "yerel_kosu_yok" not in read(root, "okuma-hatalari.json")


def test_no_local_sources_no_heartbeat_check(tmp_path):
    root = make_root(tmp_path)
    run(root, day="2026-11-14", gemini=FakeGemini(default_answers()))
    _, gh, _ = run(root, day="2026-11-20", gemini=FakeGemini(default_answers()))
    assert gh.created_issues == []


# --- --yerel modu ---


def test_local_mode_processes_only_local_sources_with_own_state_files(tmp_path):
    root = make_root(tmp_path)
    durum = root / "durum"
    durum.mkdir()
    actions_files = {
        "okuma-hatalari.json": fk.dump_json({"kaynaklar": {EXXEN_URL: {"ardisik": 1}}, "planlar": {}}),
        "sayfa-ozetleri.json": fk.dump_json({EXXEN_URL: {"karma": "a", "degisim_tarihi": "x"}}),
        "son-calisma.json": fk.dump_json({"tarih": "2026-11-10"}),
    }
    for name, content in actions_files.items():
        (durum / name).write_text(content, encoding="utf-8")

    gemini = FakeGemini(default_answers())
    summary, gh, git = run(
        root,
        gemini=gemini,
        mode=fk.MODE_LOCAL,
        local_urls=LOCAL,
        weekly=True,
        page_map={SPOTIFY_URL: pages()[SPOTIFY_URL]},
    )
    assert gemini.calls == [SPOTIFY_URL]
    assert [k["url"] for k in summary["kaynaklar"]] == [SPOTIFY_URL]
    assert summary["mod"] == "yerel" and summary["hata"] == 0
    assert "(yerel)" in fk.render_summary(summary)
    # Actions'ın dosyalarına dokunulmaz.
    for name, content in actions_files.items():
        assert (durum / name).read_text(encoding="utf-8") == content
    assert SPOTIFY_URL in read(root, "yerel-sayfa-ozetleri.json")
    heartbeat = read(root, "yerel-son-calisma.json")
    assert heartbeat["tarih"] == "2026-11-17" and heartbeat["toplam_kaynak"] == 1
    assert git.main_commits == [
        ["durum/yerel-okuma-hatalari.json", "durum/yerel-sayfa-ozetleri.json", "durum/yerel-son-calisma.json"]
    ]
    assert gh.created_issues == []  # haftalık işler yerelde çalışmaz


def test_local_mode_without_tl_counts_as_unreadable(tmp_path):
    root = make_root(tmp_path)
    dollar = {SPOTIFY_URL: "<html><body><p>Bireysel $11.99/month</p></body></html>"}
    gh = FakeGitHub()
    for i, day in enumerate(["2026-11-15", "2026-11-16", "2026-11-17"], 1):
        summary, gh, _ = run(
            root, day=day, gemini=FakeGemini(), mode=fk.MODE_LOCAL, local_urls=LOCAL, page_map=dollar, gh=gh
        )
        assert summary["kaynaklar"][0]["durum"] == "okunamadi"
        assert read(root, "yerel-okuma-hatalari.json")["kaynaklar"][SPOTIFY_URL]["ardisik"] == i
    assert not (root / "durum" / "okuma-hatalari.json").exists()
    [(title, body)] = gh.created_issues
    assert title == "Manuel kontrol: Spotify fiyat sayfası okunamıyor"
    assert "VPN" in body and "(yerel, TR)" in body


def test_local_mode_pr_says_it_came_from_local_run(tmp_path):
    root = make_root(tmp_path)
    _, gh, git = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        mode=fk.MODE_LOCAL,
        local_urls=LOCAL,
        page_map={SPOTIFY_URL: pages(b="129")[SPOTIFY_URL]},
    )
    [pr] = gh.created_prs
    assert pr["branch"] == fk.BRANCH
    assert "Kaynak koşu: yerel (TR)" in pr["body"]
    assert published_catalog(git)["servisler"][0]["planlar"][0]["fiyat_tl"] == 129


def test_actions_pr_says_actions(tmp_path):
    root = make_root(tmp_path)
    _, gh, _ = run(root, gemini=FakeGemini(default_answers(**spotify_hike())), page_map=pages(b="129"))
    assert "Kaynak koşu: GitHub Actions" in gh.created_prs[0]["body"]


# --- dal / PR yarışı ---


def other_run_opened_pr(gh, aile_price=219):
    """Diğer koşu (ör. Actions) bu arada Aile zammıyla PR açtı."""
    target = fk.collect_targets(catalog())[1]
    branch_cat, _ = fk.apply_changes(
        catalog(),
        None,
        [fk.Finding(target, float(aile_price), True, "q", 0.9, [], SPOTIFY_URL, "m")],
        "2026-11-17",
    )

    def apply(git):
        git.branch_files = {"fiyatlar.json": fk.dump_json(branch_cat)}
        git.sha = "sha-diger"
        gh.prs.append(
            {
                "number": 12,
                "title": "Fiyat güncellemesi (katalog sürümü 2)",
                "body": "Diğer koşunun gövdesi",
                "headRefName": fk.BRANCH,
                "createdAt": "2026-11-17T06:00:00Z",
                "url": "u",
            }
        )

    return apply


def test_push_rejected_reloads_branch_and_retries_once(tmp_path):
    root = make_root(tmp_path)
    gh = FakeGitHub()
    git = FakeGit(reject_pushes=1, on_reject=other_run_opened_pr(gh))
    summary, gh, git = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        page_map=pages(b="129"),
        gh=gh,
        git=git,
        mode=fk.MODE_LOCAL,
        local_urls=frozenset({SPOTIFY_URL}),
    )
    assert git.rejected[0]["from_existing"] is False and git.rejected[0]["expected_sha"] == ""
    [pub] = git.published
    assert pub["from_existing"] is True and pub["expected_sha"] == "sha-diger"
    cat = published_catalog(git)
    assert [p["fiyat_tl"] for p in cat["servisler"][0]["planlar"]] == [129, 219]  # iki koşunun değişikliği
    assert cat["surum"] == 2
    assert gh.created_prs == []
    [edit] = gh.edited_prs
    assert edit["number"] == 12 and edit["body"].startswith("Diğer koşunun gövdesi")
    assert "yerel (TR)" in edit["body"]
    assert summary["basarisiz_islemler"] == []


def test_push_rejected_twice_fails_without_pr(tmp_path):
    root = make_root(tmp_path)
    git = FakeGit(reject_pushes=2)
    summary, gh, git = run(
        root, gemini=FakeGemini(default_answers(**spotify_hike())), page_map=pages(b="129"), git=git
    )
    assert len(git.rejected) == 2 and git.published == []
    assert gh.created_prs == [] and gh.edited_prs == []
    assert any("fiyat PR" in f for f in summary["basarisiz_islemler"])


def fresh_branch_without_pr(aile_price=219):
    """Diğer koşu dalı az önce push etti (Aile zammı) ama PR'ı henüz açmadı."""
    target = fk.collect_targets(catalog())[1]
    branch_cat, _ = fk.apply_changes(
        catalog(),
        None,
        [fk.Finding(target, float(aile_price), True, "q", 0.9, [], SPOTIFY_URL, "m")],
        "2026-11-17",
    )
    git = FakeGit({"fiyatlar.json": fk.dump_json(branch_cat)})
    git.sha = "sha-taze"
    git.fresh = True
    return git


def test_fresh_branch_without_pr_is_not_overwritten(tmp_path):
    root = make_root(tmp_path)
    git = fresh_branch_without_pr()
    waits = []
    summary, gh, git = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        page_map=pages(b="129", a="219"),
        git=git,
        sleep=waits.append,
    )
    assert waits == [fk.FRESH_BRANCH_WAIT] * fk.FRESH_BRANCH_RETRIES
    [pub] = git.published
    assert pub["from_existing"] is True and pub["expected_sha"] == "sha-taze"  # dal benimsendi
    cat = published_catalog(git)
    assert [p["fiyat_tl"] for p in cat["servisler"][0]["planlar"]] == [129, 219]  # diğerinin commit'i korunur
    assert len(gh.created_prs) == 1 and summary["basarisiz_islemler"] == []


def test_fresh_branch_gets_pr_while_waiting_then_appends_to_it(tmp_path):
    root = make_root(tmp_path)
    git = fresh_branch_without_pr()
    gh = FakeGitHub()

    def sleep(seconds):
        gh.prs.append(
            {
                "number": 21,
                "title": "Fiyat güncellemesi (katalog sürümü 2)",
                "body": "diğer",
                "headRefName": fk.BRANCH,
                "createdAt": "2026-11-17T06:00:00Z",
                "url": "u",
            }
        )

    _, gh, git = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        page_map=pages(b="129", a="219"),
        git=git,
        gh=gh,
        sleep=sleep,
    )
    assert git.published[0]["from_existing"] is True
    assert gh.created_prs == [] and [e["number"] for e in gh.edited_prs] == [21]


def test_old_branch_without_pr_is_replaced_from_main(tmp_path):
    root = make_root(tmp_path)
    git = fresh_branch_without_pr()
    git.fresh = False  # ≥ 10 dk ya da main'e girmiş: eski davranış
    waits = []
    _, gh, git = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        page_map=pages(b="129"),
        git=git,
        sleep=waits.append,
    )
    assert waits == []
    [pub] = git.published
    assert pub["from_existing"] is False and pub["expected_sha"] == "sha-taze"
    assert [p["fiyat_tl"] for p in published_catalog(git)["servisler"][0]["planlar"]] == [129, 199]


def test_retry_path_also_protects_fresh_branch(tmp_path):
    root = make_root(tmp_path)
    git = FakeGit(reject_pushes=1)

    def other_pushed(g):
        fresh = fresh_branch_without_pr()
        g.branch_files, g.sha, g.fresh = fresh.branch_files, fresh.sha, True

    git.on_reject = other_pushed
    waits = []
    _, gh, git = run(
        root,
        gemini=FakeGemini(default_answers(**spotify_hike())),
        page_map=pages(b="129", a="219"),
        git=git,
        sleep=waits.append,
    )
    assert len(waits) == fk.FRESH_BRANCH_RETRIES
    [pub] = git.published
    assert pub["from_existing"] is True
    assert [p["fiyat_tl"] for p in published_catalog(git)["servisler"][0]["planlar"]] == [129, 219]


def test_create_pr_race_falls_back_to_editing_open_pr(tmp_path):
    root = make_root(tmp_path)

    class RacyGitHub(FakeGitHub):
        def create_pr(self, branch, title, body, labels):
            self.prs.append(
                {
                    "number": 13,
                    "title": "Fiyat güncellemesi",
                    "body": "önce",
                    "headRefName": branch,
                    "createdAt": "2026-11-17T06:00:00Z",
                    "url": "u",
                }
            )
            raise RuntimeError("a pull request for branch already exists")

    gh = RacyGitHub()
    summary, gh, _ = run(
        root, gemini=FakeGemini(default_answers(**spotify_hike())), page_map=pages(b="129"), gh=gh
    )
    assert [e["number"] for e in gh.edited_prs] == [13]
    assert summary["basarisiz_islemler"] == []


# --- gerçek git ile push reddi ---

IDENTITY = ("-c", "user.name=test", "-c", "user.email=test@example.com")


def sh(cwd, *args):
    return subprocess.run(
        ["git", *IDENTITY, *args], cwd=cwd, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "durum").mkdir()
    (seed / "durum" / "a.json").write_text("{}\n", encoding="utf-8")
    (seed / "fiyatlar.json").write_text("{}\n", encoding="utf-8")
    sh(seed, "add", ".")
    sh(seed, "commit", "-m", "ilk")
    sh(seed, "push", "origin", "HEAD:main")
    clones = []
    for name in ("yerel", "diger"):
        path = tmp_path / name
        subprocess.run(["git", "clone", str(origin), str(path)], check=True, capture_output=True)
        clones.append(path)
    return origin, clones[0], clones[1]


def test_commit_main_retries_once_when_push_is_rejected(repos):
    origin, mine, other = repos

    class RacyGit(fk.Git):
        raced = False

        def _push(self, *args):
            if not self.raced:  # pull --rebase ile push arasında diğer koşu main'e yazar
                self.raced = True
                (other / "durum" / "b.json").write_text('{"x": 1}\n', encoding="utf-8")
                sh(other, "add", ".")
                sh(other, "commit", "-m", "diğer")
                sh(other, "push", "origin", "HEAD:main")
            return super()._push(*args)

    logs = []
    git = RacyGit(mine, dry_run=False, log=logs.append, identity=IDENTITY)
    (mine / "durum" / "yerel-c.json").write_text('{"y": 2}\n', encoding="utf-8")
    assert git.commit_main(["durum/yerel-c.json"], "durum: yerel") is True
    assert any("reddedildi" in m for m in logs)
    assert sh(mine, "log", "--format=%s", "origin/main").split("\n")[:3] == ["durum: yerel", "diğer", "ilk"]


def test_commit_main_gives_up_after_second_rejection(repos):
    _, mine, _ = repos

    class AlwaysRejected(fk.Git):
        def _push(self, *args):
            raise fk.PushRejected("reddedildi")

    git = AlwaysRejected(mine, dry_run=False, log=lambda m: None, identity=IDENTITY)
    (mine / "durum" / "yerel-c.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(fk.PushRejected):
        git.commit_main(["durum/yerel-c.json"], "durum: yerel")


def test_publish_branch_lease_rejects_concurrent_branch(repos):
    origin, mine, other = repos
    git = fk.Git(mine, dry_run=False, log=lambda m: None, identity=IDENTITY)
    observed = git.remote_branch_sha(fk.BRANCH)
    assert observed == ""
    # Diğer koşu bu arada dalı açtı.
    sh(other, "checkout", "-b", fk.BRANCH)
    (other / "fiyatlar.json").write_text('{"diger": 1}\n', encoding="utf-8")
    sh(other, "commit", "-am", "diğer koşu")
    sh(other, "push", "origin", fk.BRANCH)

    with pytest.raises(fk.PushRejected):
        git.publish_branch(fk.BRANCH, False, {"fiyatlar.json": '{"benim": 1}\n'}, "benim", observed)
    assert sh(mine, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    # Diğer koşunun commit'i korunur.
    assert sh(other, "ls-remote", "origin", fk.BRANCH).split()[0] == sh(other, "rev-parse", "HEAD").strip()

    # Durum tazelenince (açık PR + yeni uç) dalın üzerine eklenir.
    fresh = git.remote_branch_sha(fk.BRANCH)
    assert git.read_branch_file(fk.BRANCH, "fiyatlar.json", fresh) == '{"diger": 1}\n'
    git.publish_branch(fk.BRANCH, True, {"fiyatlar.json": '{"diger": 1, "benim": 1}\n'}, "benim", fresh)
    log = sh(mine, "log", "--format=%s", f"origin/{fk.BRANCH}").split("\n")
    assert log[:3] == ["benim", "diğer koşu", "ilk"]


def test_publish_branch_replaces_stale_branch_when_no_open_pr(repos):
    origin, mine, other = repos
    sh(other, "checkout", "-b", fk.BRANCH)
    (other / "fiyatlar.json").write_text('{"eski": 1}\n', encoding="utf-8")
    sh(other, "commit", "-am", "eski kapanmış PR")
    sh(other, "push", "origin", fk.BRANCH)
    git = fk.Git(mine, dry_run=False, log=lambda m: None, identity=IDENTITY)
    sha = git.remote_branch_sha(fk.BRANCH)
    git.publish_branch(fk.BRANCH, False, {"fiyatlar.json": '{"yeni": 1}\n'}, "yeni", sha)
    log = sh(mine, "log", "--format=%s", f"origin/{fk.BRANCH}").split("\n")
    assert log[:2] == ["yeni", "ilk"]


def test_branch_is_fresh_unmerged_real_git(repos):
    origin, mine, other = repos
    sh(other, "checkout", "-b", fk.BRANCH)
    (other / "fiyatlar.json").write_text('{"diger": 1}\n', encoding="utf-8")
    sh(other, "commit", "-am", "taze")
    sh(other, "push", "origin", fk.BRANCH)
    git = fk.Git(mine, dry_run=False, log=lambda m: None, identity=IDENTITY)
    sha = git.remote_branch_sha(fk.BRANCH)
    committed = int(sh(other, "show", "-s", "--format=%ct", "HEAD").strip())
    assert git.branch_is_fresh_unmerged(sha, now=committed + 60) is True
    assert git.branch_is_fresh_unmerged(sha, now=committed + fk.FRESH_BRANCH_SECONDS + 1) is False
    # main'e birleştirilmiş dal taze sayılmaz.
    sh(other, "push", "origin", f"{fk.BRANCH}:main")
    assert git.branch_is_fresh_unmerged(sha, now=committed + 60) is False


def test_commit_main_returns_to_main_first(repos):
    _, mine, _ = repos
    sh(mine, "checkout", "-b", fk.BRANCH)
    git = fk.Git(mine, dry_run=False, log=lambda m: None, identity=IDENTITY)
    (mine / "durum" / "yerel-c.json").write_text("{}\n", encoding="utf-8")
    assert git.commit_main(["durum/yerel-c.json"], "durum: yerel") is True
    assert sh(mine, "rev-parse", "--abbrev-ref", "HEAD").strip() == "main"
    assert sh(mine, "log", "-1", "--format=%s", "origin/main").strip() == "durum: yerel"


# --- main(): anahtar yok ---


def test_local_run_without_key_exits_with_clear_error(monkeypatch, capsys):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(fk, "Runner", None)  # çağrılırsa test patlar
    assert fk.main(["--yerel"]) == fk.EXIT_NO_KEY
    err = capsys.readouterr().err
    assert "GEMINI_API_KEY" in err and "setx" in err


# --- gerçek veri ---


@pytest.mark.veri
def test_local_sources_exist_in_catalog():
    urls = fk.load_local_sources()
    assert urls == {
        "https://help.netflix.com/tr/node/24926",
        "https://www.youtube.com/premium?hl=tr&gl=TR",
        "https://www.amazon.com.tr/gp/help/customer/display.html?nodeId=G34EUPKVMYFW8N2U",
        "https://one.google.com/about/plans?hl=tr&gl=TR",
        "https://mubi.com/tr/subscribe",
        "https://www.youtube.com/musicpremium?hl=tr&gl=TR",
    }
    catalog_urls = set(fk.group_by_url(fk.collect_targets(fk.load_json(REPO / "fiyatlar.json"))))
    assert urls <= catalog_urls
