"""
Training-materials access model: any authenticated agent may browse and download;
only admins may create / edit / delete / upload. Materials support many files and
per-company visibility; safe files render inline for preview.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.models.models import Base, Agent, Role, TrainingMaterial
from app.security import hash_password


@pytest.fixture
def client():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    s = Session()

    def mk(code, role, company="heritree"):
        a = Agent(code=code, name=code, email=f"{code}@x.com", level=1, role=role,
                  company=company, password_hash=hash_password("pw"))
        s.add(a); s.flush()
        return a

    adm = mk("ADM", Role.ADMIN)
    ax = mk("AX", Role.AGENT, "heritree")
    cpm = mk("cpm1", Role.AGENT, "cpm")
    s.commit()
    ids = {"adm": adm.id, "ax": ax.id, "cpm": cpm.id}
    s.close()

    from app import main
    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()
    main.app.dependency_overrides[main.get_db] = override_get_db
    tc = TestClient(main.app)
    tc._ids = ids
    tc._Session = Session
    yield tc
    main.app.dependency_overrides.clear()


def auth(tc, code):
    r = tc.post("/auth/login", json={"username": code, "password": "pw"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def mk_material(tc, headers, **kw):
    payload = {"title": "Onboarding 101", "category": "新人入職"}
    payload.update(kw)
    return tc.post("/training-materials", headers=headers, json=payload)


def _upload(tc, headers, mid, *files):
    """files: (name, bytes, ctype) tuples, all under the `files` field."""
    return tc.post(f"/training-materials/{mid}/files", headers=headers,
                   files=[("files", f) for f in files])


def test_thumbnail_generated_for_image_and_pdf(client):
    """A real PNG and a real PDF each get a small JPEG thumbnail; a non-thumbnailable
    file 404s (the UI falls back to a type tile)."""
    import io
    pytest.importorskip("PIL")
    try:
        import pymupdf as fitz
    except Exception:
        fitz = pytest.importorskip("fitz")
    from PIL import Image

    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]

    # real 40x30 PNG
    buf = io.BytesIO(); Image.new("RGB", (40, 30), (12, 34, 56)).save(buf, "PNG")
    png = buf.getvalue()
    # real 1-page PDF
    doc = fitz.open(); doc.new_page(width=200, height=280); pdf = doc.tobytes()

    up = _upload(client, adm, mid,
                 ("pic.png", png, "image/png"),
                 ("doc.pdf", pdf, "application/pdf"),
                 ("data.bin", b"\x00\x01\x02not-media", "application/octet-stream"))
    assert up.status_code == 200, up.text
    files = {f["file_name"]: f["id"] for f in up.json()["files"]}

    for name in ("pic.png", "doc.pdf"):
        r = client.get(f"/training-materials/{mid}/files/{files[name]}/thumb", headers=ax)
        assert r.status_code == 200, (name, r.text)
        assert r.headers["content-type"] == "image/jpeg"
        assert r.content[:2] == b"\xff\xd8"          # JPEG magic
        assert 0 < len(r.content) < 200_000

    # non-media file has no thumbnail
    assert client.get(f"/training-materials/{mid}/files/{files['data.bin']}/thumb",
                      headers=ax).status_code == 404


def test_thumbnail_scoped_by_company(client):
    adm, cpm = auth(client, "ADM"), auth(client, "cpm1")
    import io
    pytest.importorskip("PIL")
    from PIL import Image
    mid = mk_material(client, adm, companies=["heritree"]).json()["id"]
    buf = io.BytesIO(); Image.new("RGB", (20, 20), (1, 2, 3)).save(buf, "PNG")
    fid = _upload(client, adm, mid, ("p.png", buf.getvalue(), "image/png")).json()["files"][0]["id"]
    # a CPM agent can't see a heritree-only material's thumbnail
    assert client.get(f"/training-materials/{mid}/files/{fid}/thumb", headers=cpm).status_code == 404


def test_video_range_streaming_and_token_auth(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    data = b"\x00\x00\x00\x18ftypmp42" + b"A" * 500
    fid = _upload(client, adm, mid, ("v.mp4", data, "video/mp4")).json()["files"][0]["id"]
    path = f"/training-materials/{mid}/files/{fid}"

    full = client.get(path, headers=ax)
    assert full.status_code == 200
    assert full.headers.get("accept-ranges") == "bytes"      # seekable
    assert len(full.content) == len(data)

    r = client.get(path, headers={**ax, "Range": "bytes=0-99"})
    assert r.status_code == 206                               # partial content
    assert r.headers["content-range"] == f"bytes 0-99/{len(data)}"
    assert len(r.content) == 100

    # <video> can't send headers → JWT in a query param must authenticate
    tok = ax["Authorization"].split()[1]
    assert client.get(f"{path}?token={tok}").status_code == 200
    assert client.get(path).status_code == 401               # no creds at all


def test_video_transcode_scheduling_and_serving(client, monkeypatch):
    from app import main
    from app.models.models import TrainingFile
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]

    scheduled = []
    monkeypatch.setattr(main, "_maybe_transcode_video", lambda fid: scheduled.append(fid))

    data = b"\x00\x00\x00\x18ftypisom" + b"H" * 400
    fid = _upload(client, adm, mid, ("v.mp4", data, "video/mp4")).json()["files"][-1]["id"]
    assert fid in scheduled                                   # upload scheduled a transcode

    # simulate a finished transcode by storing an H.264 preview stream
    with client._Session() as db:
        row = db.get(TrainingFile, fid)
        row.preview_data = b"H264-TRANSCODED-BYTES"
        row.preview_content_type = "video/mp4"
        db.commit()

    inline = client.get(f"/training-materials/{mid}/files/{fid}", headers=ax)
    assert inline.status_code == 200 and inline.content == b"H264-TRANSCODED-BYTES"   # serves H.264
    assert inline.headers["content-type"].startswith("video/")
    orig = client.get(f"/training-materials/{mid}/files/{fid}?download=1", headers=ax)
    assert orig.content == data                               # download still the original

    # transcode-pending skips a video that already has an H.264 preview
    scheduled.clear()
    r = client.post("/training-materials/transcode-pending", headers=adm)
    assert r.status_code == 200 and r.json()["scheduled"] == 0 and fid not in scheduled


def test_transcode_pending_admin_only(client):
    assert client.post("/training-materials/transcode-pending",
                       headers=auth(client, "AX")).status_code == 403


def test_simplified_input_converted_to_traditional(client):
    adm = auth(client, "ADM")
    r = mk_material(client, adm, title="香港分红险", category="产品知识",
                    description="<p>产品优势</p>")
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["title"] == "香港分紅險"
    assert m["category"] == "產品知識"
    assert "產品優勢" in m["description"] and "产品优势" not in m["description"]


def test_convert_existing_backfill(client):
    from app.models.models import Product, ProductType
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    with client._Session() as db:
        db.add(TrainingMaterial(title="产品优势", category="产品知识", description="<p>网络覆盖</p>"))
        db.add(Product(code="INS-X-1", name="环宇盈活", type=list(ProductType)[0]))
        db.commit()

    assert client.post("/admin/convert-existing", headers=ax).status_code == 403  # admin only
    r = client.post("/admin/convert-existing", headers=adm)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["changed"]["training_materials"] >= 1 and body["changed"]["products"] >= 1

    m = next(x for x in client.get("/training-materials", headers=adm).json() if x["title"] == "產品優勢")
    assert m["category"] == "產品知識" and "網絡覆蓋" in m["description"]
    p = next(x for x in client.get("/products", headers=ax).json() if x["code"] == "INS-X-1")
    assert p["name"] == "環宇盈活"
    # idempotent: a second run changes nothing
    assert client.post("/admin/convert-existing", headers=adm).json()["total"] == 0


def test_reorder_materials(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    ids = [mk_material(client, adm, title=f"M{i}").json()["id"] for i in range(3)]
    listed = [m["id"] for m in client.get("/training-materials", headers=adm).json()]
    assert listed == ids                                     # default = creation order

    rev = list(reversed(ids))
    assert client.put("/training-materials/order", headers=adm, json=rev).status_code == 200
    listed2 = [m["id"] for m in client.get("/training-materials", headers=adm).json()]
    assert listed2 == rev                                    # custom order honoured

    assert client.put("/training-materials/order", headers=ax, json=ids).status_code == 403  # admin only


def test_admin_creates_and_agent_reads(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    r = mk_material(client, adm, link_url="https://example.com/guide.pdf")
    assert r.status_code == 200, r.text
    mid = r.json()["id"]
    rows = client.get("/training-materials", headers=ax).json()
    assert any(m["id"] == mid for m in rows)
    assert rows[0]["has_file"] is False and rows[0]["files"] == []


def test_inline_preview_flag_roundtrips(client):
    adm = auth(client, "ADM")
    r = mk_material(client, adm, inline_preview=True)
    assert r.status_code == 200 and r.json()["inline_preview"] is True
    mid = r.json()["id"]
    upd = client.patch(f"/training-materials/{mid}", headers=adm, json={"inline_preview": False})
    assert upd.json()["inline_preview"] is False
    # default is False when omitted
    assert mk_material(client, adm).json()["inline_preview"] is False


def test_remark_html_is_sanitized(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    dirty = ('<p>Read <strong>this</strong></p><script>alert(1)</script>'
             '<img src=x onerror=alert(1)><a href="javascript:alert(1)">x</a>')
    mid = mk_material(client, adm, description=dirty).json()["id"]
    html = next(m for m in client.get("/training-materials", headers=ax).json()
                if m["id"] == mid)["description"]
    assert "<strong>this</strong>" in html          # formatting kept
    assert "<script" not in html and "onerror" not in html   # scripts/handlers gone
    assert "javascript:" not in html                # dangerous href stripped
    # sanitised again on PATCH
    upd = client.patch(f"/training-materials/{mid}", headers=adm,
                       json={"description": "<b onclick=\"e()\">hi</b>"}).json()
    assert upd["description"] == "<b>hi</b>"


def test_remark_images_allowed_but_scoped(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    body = ('<img src="https://x.com/a.png" alt="ok">'
            '<img src="data:image/png;base64,iVBOR">'
            '<img src="data:image/svg+xml;base64,PHN2Zz4=">'   # svg dropped
            '<img src="javascript:alert(1)">')                 # unsafe dropped
    mid = mk_material(client, adm, description=body).json()["id"]
    html = next(m for m in client.get("/training-materials", headers=ax).json()
                if m["id"] == mid)["description"]
    assert 'src="https://x.com/a.png"' in html
    assert "data:image/png;base64,iVBOR" in html
    assert "svg" not in html and "javascript:" not in html
    assert html.count("<img") == 2


def test_agent_cannot_write(client):
    ax = auth(client, "AX")
    assert mk_material(client, ax).status_code == 403
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    assert client.patch(f"/training-materials/{mid}", headers=ax,
                        json={"title": "x"}).status_code == 403
    assert client.delete(f"/training-materials/{mid}", headers=ax).status_code == 403


def test_multi_file_upload_and_serve(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    up = _upload(client, adm, mid,
                 ("a.pdf", b"%PDF-1.4 aaa", "application/pdf"),
                 ("b.png", b"\x89PNG bbb", "image/png"))
    assert up.status_code == 200, up.text
    files = up.json()["files"]
    assert up.json()["has_file"] and len(files) == 2
    assert {f["file_name"] for f in files} == {"a.pdf", "b.png"}
    # append a third file
    up2 = _upload(client, adm, mid, ("c.pdf", b"%PDF ccc", "application/pdf"))
    assert len(up2.json()["files"]) == 3
    # any agent can fetch a file's bytes by id
    fid = files[0]["id"]
    dl = client.get(f"/training-materials/{mid}/files/{fid}", headers=ax)
    assert dl.status_code == 200 and dl.content == b"%PDF-1.4 aaa"


def test_pdf_previews_inline_but_download_forces_attachment(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    fid = _upload(client, adm, mid, ("g.pdf", b"%PDF g", "application/pdf")).json()["files"][0]["id"]
    inline = client.get(f"/training-materials/{mid}/files/{fid}", headers=ax)
    assert inline.headers["content-disposition"].startswith("inline")
    dl = client.get(f"/training-materials/{mid}/files/{fid}?download=1", headers=ax)
    assert dl.headers["content-disposition"].startswith("attachment")
    # video previews inline too
    vfid = _upload(client, adm, mid, ("c.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")).json()["files"][-1]["id"]
    vr = client.get(f"/training-materials/{mid}/files/{vfid}", headers=ax)
    assert vr.headers["content-disposition"].startswith("inline")
    assert vr.headers["content-type"].startswith("video/mp4")
    # a non-preview type always downloads
    fid2 = _upload(client, adm, mid, ("x.bin", b"data", "application/octet-stream")).json()["files"][-1]["id"]
    assert client.get(f"/training-materials/{mid}/files/{fid2}", headers=ax
                      ).headers["content-disposition"].startswith("attachment")


PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def test_office_doc_previews_as_rendered_pdf(client, monkeypatch):
    """An uploaded PPTX gets a rendered-PDF preview; preview serves the PDF inline,
    download serves the original PPTX."""
    import app.main as main
    monkeypatch.setattr(main, "_office_to_pdf", lambda data, name: b"%PDF-1.4 rendered")
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    f = _upload(client, adm, mid, ("deck.pptx", b"PK fake pptx", PPTX)).json()["files"][0]
    assert f["preview_content_type"] == "application/pdf"
    pv = client.get(f"/training-materials/{mid}/files/{f['id']}", headers=ax)
    assert pv.headers["content-disposition"].startswith("inline")
    assert pv.headers["content-type"].startswith("application/pdf")
    assert pv.content == b"%PDF-1.4 rendered"
    dl = client.get(f"/training-materials/{mid}/files/{f['id']}?download=1", headers=ax)
    assert dl.headers["content-disposition"].startswith("attachment")
    assert dl.content == b"PK fake pptx"


def test_office_doc_without_libreoffice_downloads(client, monkeypatch):
    """When conversion is unavailable (no LibreOffice), the doc has no preview and
    is served as a download."""
    import app.main as main
    monkeypatch.setattr(main, "_office_to_pdf", lambda data, name: None)
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    f = _upload(client, adm, mid, ("d.pptx", b"PK", PPTX)).json()["files"][0]
    assert f["preview_content_type"] is None
    assert client.get(f"/training-materials/{mid}/files/{f['id']}", headers=ax
                      ).headers["content-disposition"].startswith("attachment")


def test_company_visibility(client):
    adm, ax, cpm = auth(client, "ADM"), auth(client, "AX"), auth(client, "cpm1")
    # CPM-only, Heritree-only, and both/all
    cpm_only = mk_material(client, adm, title="CPM only", companies=["cpm"]).json()["id"]
    her_only = mk_material(client, adm, title="Heritree only", companies=["heritree"]).json()["id"]
    everyone = mk_material(client, adm, title="Everyone").json()["id"]  # companies None
    ax_ids = {m["id"] for m in client.get("/training-materials", headers=ax).json()}
    cpm_ids = {m["id"] for m in client.get("/training-materials", headers=cpm).json()}
    assert her_only in ax_ids and everyone in ax_ids and cpm_only not in ax_ids
    assert cpm_only in cpm_ids and everyone in cpm_ids and her_only not in cpm_ids
    # admin sees all regardless of company
    adm_ids = {m["id"] for m in client.get("/training-materials", headers=adm).json()}
    assert {cpm_only, her_only, everyone} <= adm_ids


def test_company_scoped_file_access(client):
    adm, cpm = auth(client, "ADM"), auth(client, "cpm1")
    mid = mk_material(client, adm, companies=["heritree"]).json()["id"]
    fid = _upload(client, adm, mid, ("h.pdf", b"%PDF h", "application/pdf")).json()["files"][0]["id"]
    # a CPM agent can't fetch a Heritree-only material's file
    assert client.get(f"/training-materials/{mid}/files/{fid}", headers=cpm).status_code == 404


def test_agent_cannot_upload_or_delete_file(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    assert _upload(client, ax, mid, ("x.pdf", b"data", "application/pdf")).status_code == 403
    fid = _upload(client, adm, mid, ("y.pdf", b"data", "application/pdf")).json()["files"][0]["id"]
    assert client.delete(f"/training-materials/{mid}/files/{fid}", headers=ax).status_code == 403


def test_oversize_upload_rejected(client):
    import app.main as main
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    too_big = b"x" * (main.TRAINING_MAX_UPLOAD_MB * 1024 * 1024 + 1)
    r = _upload(client, adm, mid, ("big.bin", too_big, "application/octet-stream"))
    assert r.status_code == 400 and r.headers.get("X-Error-Code") == "file_too_large"


def test_serve_non_ascii_filename(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    mid = mk_material(client, adm).json()["id"]
    fid = _upload(client, adm, mid, ("香港分紅保單.pdf", b"%PDF cn", "application/pdf")).json()["files"][0]["id"]
    dl = client.get(f"/training-materials/{mid}/files/{fid}", headers=ax)
    assert dl.status_code == 200 and dl.content == b"%PDF cn"
    cd = dl.headers["content-disposition"]
    assert "filename*=UTF-8''" in cd and "%E9%A6%99" in cd


def test_remove_one_file(client):
    adm = auth(client, "ADM")
    mid = mk_material(client, adm).json()["id"]
    files = _upload(client, adm, mid,
                    ("a.pdf", b"a", "application/pdf"),
                    ("b.pdf", b"b", "application/pdf")).json()["files"]
    r = client.delete(f"/training-materials/{mid}/files/{files[0]['id']}", headers=adm)
    assert r.status_code == 200
    remaining = {f["id"] for f in r.json()["files"]}
    assert remaining == {files[1]["id"]}
    assert client.get(f"/training-materials/{mid}/files/{files[0]['id']}", headers=adm).status_code == 404


def test_category_crud_and_gating(client):
    adm, ax = auth(client, "ADM"), auth(client, "AX")
    assert client.get("/training-categories", headers=ax).status_code == 200
    assert client.post("/training-categories", headers=ax, json={"name": "X"}).status_code == 403
    r = client.post("/training-categories", headers=adm, json={"name": "產品知識"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    dup = client.post("/training-categories", headers=adm, json={"name": "產品知識"})
    assert dup.status_code == 409 and dup.headers.get("X-Error-Code") == "duplicate"
    assert client.patch(f"/training-categories/{cid}", headers=adm,
                        json={"name": "產品培訓"}).json()["name"] == "產品培訓"
    assert client.delete(f"/training-categories/{cid}", headers=adm).status_code == 200
    assert all(c["id"] != cid for c in client.get("/training-categories", headers=ax).json())
