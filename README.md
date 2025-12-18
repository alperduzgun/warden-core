# Warden Core

Warden Core - AI Code Guardian Core Library

## Memory System

This project uses **Qdrant Cloud** with Azure OpenAI embeddings for enterprise-grade memory management with semantic search capabilities.

### Available Commands

- `/mem-search <query>` - Search project memory using semantic search
- `/mem-save <content>` - Save information to memory
- `/mem-context` - Load project context

### Setup

#### Prerequisites

**No local setup required!** This project uses Qdrant Cloud (managed service).

#### Configuration

Memory is configured in `.claude/config.json`:
- **Backend**: Qdrant Cloud (GCP Europe West 3)
- **Collection**: `warden_core_memories`
- **Embedding Model**: Azure OpenAI `text-embedding-ada-002`
- **Vector Dimension**: 1536
- **TLS**: Enabled

### Features

- **Semantic Search**: Find relevant memories using natural language queries with Azure OpenAI embeddings
- **Cloud Storage**: All memories stored in Qdrant Cloud (persistent, managed, no local setup)
- **Project-Specific**: Isolated memory space for warden-core project
- **Enterprise-Grade**: Azure OpenAI + Qdrant Cloud for production-ready memory
- **Highly Available**: Managed cloud infrastructure with automatic backups
- **Scalable**: Can handle large amounts of project context and notes
