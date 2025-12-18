# Warden Core

Warden Core - AI Code Guardian Core Library

## Memory System

This project uses Qdrant vector database for advanced memory management with semantic search capabilities.

### Available Commands

- `/mem-search <query>` - Search project memory using semantic search
- `/mem-save <content>` - Save information to memory
- `/mem-context` - Load project context

### Setup

#### Prerequisites

1. **Qdrant** must be running on `localhost:6333`
   ```bash
   docker run -p 6333:6333 -p 6334:6334 \
     -v $(pwd)/qdrant_storage:/qdrant/storage:z \
     qdrant/qdrant
   ```

2. The collection `warden_core_memories` is automatically created on first use.

#### Configuration

Memory is configured in `.claude/config.json`:
- Backend: Qdrant
- Collection: `warden_core_memories`
- Embedding Model: `sentence-transformers/all-MiniLM-L6-v2`
- Vector Dimension: 384

### Features

- **Semantic Search**: Find relevant memories using natural language queries
- **Persistent Storage**: All memories stored in Qdrant vector database
- **Project-Specific**: Isolated memory space for this project
- **Scalable**: Can handle large amounts of project context and notes
