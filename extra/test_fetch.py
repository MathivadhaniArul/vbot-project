from huggingface_hub import hf_hub_download

files = [
    "tokenizer.json",
    "tokenizer_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json"
]

for f in files:
    hf_hub_download(
        repo_id="BAAI/bge-m3",
        filename=f,
        local_dir="C:/Users/mathi/Downloads/bge-download",
        local_dir_use_symlinks=False,
    )