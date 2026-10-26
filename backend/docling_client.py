import requests
import pandas as pd
from pathlib import Path
from typing import Optional


class DoclingClient:
    def __init__(self, base_url: str = "http://localhost:8004", timeout: int = 550, do_ocr: bool = False):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.do_ocr = do_ocr

    def convert(self, file_path: str, include_chunks: bool = True) -> dict:
        with open(file_path, "rb") as f:
            response = requests.post(
                f"{self.base_url}/convert",
                files={"file": f},
                params={"do_ocr": self.do_ocr, "include_chunks": include_chunks},
                timeout=self.timeout,
            )
        response.raise_for_status()
        return response.json()

    def to_markdown(self, file_path: str, save_path: Optional[str] = None) -> str:
        data = self.convert(file_path, include_chunks=False)
        if save_path:
            Path(save_path).write_text(data["markdown"], encoding="utf-8")
        return data["markdown"]

    def get_tables(self, file_path: str) -> list[pd.DataFrame]:
        data = self.convert(file_path, include_chunks=False)
        return [pd.DataFrame(t) for t in data["tables"]]

    def get_chunks(self, file_path: str) -> list[dict]:
        data = self.convert(file_path, include_chunks=True)
        return data["chunks"]

    def health(self) -> dict:
        return requests.get(f"{self.base_url}/health", timeout=10).json()