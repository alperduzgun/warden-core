# ID 40: Fix OrphanFrame LSP False Advertising

Update detect_all to:
1. Check use_lsp config flag
2. Call async implementation properly
3. Don't hardcode use_lsp=False
