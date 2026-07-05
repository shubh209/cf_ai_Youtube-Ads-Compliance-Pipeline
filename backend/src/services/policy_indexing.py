import glob
import os
import uuid
from datetime import datetime, timezone

from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy.orm import Session

from backend.src.db.models import PolicyVersion
from backend.src.services.policy_store import get_vector_store


def run_policy_index(db: Session | None = None) -> dict:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_folder = os.path.join(current_dir, "..", "..", "data")
    pdf_files = glob.glob(os.path.join(data_folder, "*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDFs found in {data_folder}")

    all_splits = []
    for pdf_path in pdf_files:
        loader = PyPDFLoader(pdf_path)
        raw_docs = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = splitter.split_documents(raw_docs)
        for split in splits:
            split.metadata["chunk_id"] = str(uuid.uuid4())
            split.metadata["source"] = os.path.basename(pdf_path)
            split.metadata["platform"] = "youtube"  # default for existing PDFs
        all_splits.extend(splits)

    store = get_vector_store()
    store.add_documents(documents=all_splits)

    version_label = datetime.now(timezone.utc).strftime("v%Y%m%d-%H%M%S")
    result = {"version_label": version_label, "chunk_count": len(all_splits), "policy_version_id": None}

    if db is not None:
        db.query(PolicyVersion).filter(PolicyVersion.is_current.is_(True)).update({"is_current": False})
        policy_version = PolicyVersion(
            version_label=version_label,
            chunk_count=len(all_splits),
            is_current=True,
        )
        db.add(policy_version)
        db.commit()
        db.refresh(policy_version)
        result["policy_version_id"] = str(policy_version.id)

    return result
