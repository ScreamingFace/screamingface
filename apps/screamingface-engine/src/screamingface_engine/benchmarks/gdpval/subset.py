"""The frozen GDPval text-subset selection — the 102 tasks this board serves.

Provenance: the 220-task open gold set (openai/gdpval) filtered to tasks whose reference
AND deliverable formats are all prose — {.docx, .doc, .txt, .md, .pdf}, or absent — which
yields 109; then minus the 7 whose reference files cannot be extracted to text. Both figures
were measured on 2026-08-24 over the published parquet, every row, not a sample.

INVARIANT: this tuple is FROZEN. subset_sha() participates in the board's revision hash,
so any edit re-addresses every route — an expression written against the old revision
physically cannot resolve against a changed selection. Never regenerate it from live data.

AIDEV-NOTE: the exclusions below are not a style choice. A task whose reference PDF is a
scanned image extracts to nothing; the model then cannot do the work, and the resulting low
score reads as model weakness rather than as a broken input. Serving it would corrupt exactly
the comparison this benchmark exists to make.
"""

from __future__ import annotations

import hashlib

# WHY: GDPval task_ids, not Engine Case ids — this board's identity IS a selection out of
# the 220, so the dataset's own stable ids are the honest fingerprint. HealthBench's worst30
# board does the same with HF row ids.
TEXT_SUBSET_TASK_IDS: tuple[str, ...] = (
    "0112fc9b-c3b2-4084-8993-5a4abb1f54f1",
    "02314fc6-a24e-42f4-a8cd-362cae0f0ec1",
    "0353ee0c-18b5-4ad3-88e8-e001d223e1d7",
    "045aba2e-4093-42aa-ab7f-159cc538278c",
    "05389f78-589a-473c-a4ae-67c61050bfca",
    "0818571f-5ff7-4d39-9d2c-ced5ae44299e",
    "0e4fe8cd-16d0-4f41-8247-6385b4762582",
    "0ec25916-1b5c-4bfe-93d3-4e103d860f3a",
    "116e791e-890c-42b1-ba90-1db02e8bfd45",
    "11e1b169-5fb6-4d79-8a83-82ddf4987a85",
    "15ddd28d-8445-4baa-ac7f-f41372e1344e",
    "1a78e076-445e-4c5d-b8ce-387d2fe5e715",
    "1aecc095-4d76-4b89-b752-1a0f870502cd",
    "1b1ade2d-f9f6-4a04-baa5-aa15012b53be",
    "1bff4551-1d54-4e37-b2e0-d5c3f2ea4a45",
    "1e5a1d7f-12c1-48c6-afd9-82257b3f2409",
    "211d0093-2c64-4bd0-828c-0201f18924e7",
    "22c0809b-f8db-489e-93b3-b4da225e3e0e",
    "2696757c-1f8a-4959-8f0d-f5597b9e70fc",
    "27e8912c-8bd5-44ba-ad87-64066ea05264",
    "2d06bc0a-89c6-4e89-9417-5ffe725c1bc6",
    "2fa8e956-7b35-4c13-95dc-027f02be318b",
    "36d567ba-e205-4313-9756-931c6e4691fe",
    "3a4c347c-4aec-43c7-9a54-eb1f816ab1f9",
    "3f625cb2-f40e-4ead-8a97-6924356d5989",
    "401a07f1-d57e-4bb0-889b-22de8c900f0e",
    "46bc7238-3501-4839-b989-e2bd47853676",
    "476db143-163a-4537-9e21-fe46adad703b",
    "4c4dc603-c21c-4284-8fb1-1b827c1fddf4",
    "4de6a529-4f61-41a1-b2dc-64951ba03457",
    "575f8679-b4c1-47a2-8e96-d570d4ed9269",
    "58ac1cc5-5754-4580-8c9c-8c67e1a9d619",
    "5ad0c554-a7a2-48cd-b41a-ebc1bff4a9de",
    "5d0feb24-e8b6-4ace-b64f-d5cd1a8b563d",
    "60221cd0-686e-4a08-985e-d9bb2fa18501",
    "6074bba3-7e3a-4b1c-b8c6-a15bb6695c3b",
    "61717508-4df7-41be-bf97-318dfb2475c0",
    "61f546a8-c374-467f-95cc-d0d9b5656eb6",
    "6241e678-4ba3-4831-b3c7-78412697febc",
    "6436ff9e-c5f2-47ba-9aaa-49d89b0594ab",
    "6974adea-8326-43fa-8187-2724b15d9546",
    "69a8ef86-4e69-4fe2-9168-080f1e978e67",
    "74d6e8b0-f334-4e7e-af55-c095d5d4d1a6",
    "74ed1dc7-1468-48a8-9071-58775c0d667a",
    "76d10872-9ffa-4ede-83ee-e0f1ec5e2b8d",
    "772e7524-174e-4c88-957e-6e510b61ea69",
    "788d2bc6-82df-4dc7-8467-a0f31405dc14",
    "8079e27d-b6f3-4f75-a9b5-db27903c798d",
    "8314d1b1-5b0f-42a4-b5d5-91c0867b0913",
    "8384083a-c31b-4194-80ba-4d335a444918",
    "84322284-5c2c-4873-b507-b147449d209d",
    "85d95ce5-b20c-41e2-834e-e788ce9622b6",
    "8a7b6fca-60cc-4ae3-b649-971753cbf8b9",
    "8c823e32-537c-42b2-84ba-635d63c2853a",
    "8c8fc328-69fc-4559-a13f-82087baef0a1",
    "8f9e8bcd-6102-40da-ab76-23f51d8b21fa",
    "90f37ff3-e4ed-4a0b-94bb-bed0f7def1ef",
    "91060ff0-3eb5-4ddf-9edb-f6758b95499e",
    "93b336f3-61f3-4287-86d2-87445e1e0f90",
    "99ac6944-4ec6-4848-959c-a460ac705c6f",
    "9a8c8e28-ce76-408b-83c3-488422892e58",
    "9e8607e7-a38a-491f-ace1-e5ea7dc477cb",
    "9efbcd35-186d-49b6-ac24-28ee2bc9a263",
    "a0ef404e-82a6-4507-bff1-633d7c8e0004",
    "a10ec48c-168e-476c-8fe3-23b2a5f616ac",
    "a1963a68-1bea-4bb1-b7e0-145c92a57449",
    "a328feea-47db-4856-b4be-2bdc63dd88fb",
    "a4a9195c-5ebe-4b8d-a0c2-4a6b7a49da8b",
    "a95a5829-34bb-40f3-993b-558aed6dcdef",
    "a97369c7-e5cf-40ca-99e8-d06f81c57d53",
    "aad21e4c-1d43-45fc-899a-97754a1b1b63",
    "ab81b076-e5d8-473a-9bdb-7ea7c38f6ebc",
    "ae0c1093-5ea8-4b84-a81e-53ebf7a4321d",
    "afe56d05-dac8-47d7-a233-ad1d035ca5bd",
    "b1a79ce1-86b0-41fb-97dc-9206dfd7b044",
    "b3573f20-5d3e-4954-948f-9461fda693d2",
    "b78fd844-db76-448e-a783-5e9877cb74c2",
    "bb499d9c-0263-4684-9238-75e8e86077b1",
    "bbe0a93b-ebf0-40b0-98dc-8d9243099034",
    "bd72994f-5659-4084-9fab-fc547d1efe3b",
    "c2e8f271-7858-412f-b460-472463ad81d9",
    "c9bf9801-9640-45fa-8166-1ab01f2d98e4",
    "cd9efc18-d14a-4f69-8531-5d178a08084d",
    "cebf301e-5ea7-41ae-b117-ad8f43e7ac22",
    "d025a41c-c439-4ee1-bc79-dd5c94b27a2d",
    "d3d255b2-f5f2-4841-9f62-2083ec9ef3da",
    "e14e32ba-d310-4d45-9b8a-6d73d0ece1ae",
    "e21cd746-404d-4602-b9d2-01d2812c5b87",
    "eb54f575-93f9-408b-b9e0-f1208a0b6759",
    "ec2fccc9-b7f6-4c73-bf51-896fdb433cec",
    "ef8719da-18e5-4bfe-b986-399652d77376",
    "f1be6436-ffff-4fee-9e66-d550291a1735",
    "f3351922-dbdd-45da-85c5-e7110696bbe5",
    "f5d428fd-b38e-41f0-8783-35423dab80f6",
    "f84ea6ac-8f9f-428c-b96c-d0884e30f7c7",
    "f9a1c16c-53fd-4c8f-88cc-5c325ec2f0bb",
    "f9f82549-fdde-4462-aff8-e70fba5b8c66",
    "fccaa4a1-1c39-49ac-b701-55361a19966b",
    "fd3ad420-6f7d-43b1-a990-c0c5c047d071",
    "fd6129bd-f095-429b-873c-dcc3137be2c3",
    "feb5eefc-39f1-4451-9ef9-bffe011b71dd",
    "ffed32d8-d192-4e3f-8cd4-eda5a730aec3",
)

# WHY: extraction was attempted on all 85 reference files carried by the 109 prose-only tasks
# (pdfplumber for PDF, python-docx for DOCX). 77 extracted cleanly; 6 returned under 200
# characters — scanned-image PDFs such as a 1099-INT and a mortgage form, plus a docx holding
# only a logo — and 2 raised XMLSyntaxError. At task level that is 102 clean, 5 partially
# degraded, 2 total loss.
EXCLUDED_TASK_IDS: dict[str, str] = {
    "46b34f78-6c06-4416-87e2-77b6d8b20ce9": "every reference file extracted to near-empty text",
    "55ddb773-23a4-454c-8704-d432fe1b99d9": "every reference file extracted to near-empty text",
    "43dc9778-450b-4b46-b77e-b6d82b202035": "a reference file extracted to near-empty text",
    "a45bc83b-22f9-4def-8d89-9c5661b2b86f": "a reference file extracted to near-empty text",
    "cecac8f9-8203-4ebd-ad49-54436a8c4171": "a reference file extracted to near-empty text",
    "01d7e53e-0513-4109-a242-8ccaf442cd21": "at least one reference file raised XMLSyntaxError",
    "7151c60a-d4cb-4fc4-8169-3d4cb446e6b9": "at least one reference file raised XMLSyntaxError",
}


def subset_sha() -> str:
    """Fingerprint the selection, in serve order.

    INVARIANT: order participates. Two boards serving the same tasks in a different order are
    different exams, because Engine Case ids are the 1-based positions of this tuple.
    """

    return hashlib.sha256("\n".join(TEXT_SUBSET_TASK_IDS).encode()).hexdigest()


__all__ = ["EXCLUDED_TASK_IDS", "TEXT_SUBSET_TASK_IDS", "subset_sha"]
