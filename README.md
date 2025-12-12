# GCP HCP CLI

A command-line interface for Google Cloud Platform Hosted Control Planes, providing gcloud-style commands for managing clusters and nodepools.

[![PyPI version](https://badge.fury.io/py/gcphcp.svg)](https://badge.fury.io/py/gcphcp)
[![Python Support](https://img.shields.io/pypi/pyversions/gcphcp.svg)](https://pypi.org/project/gcphcp/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

## Features

- **gcloud-style interface**: Familiar command structure and output formatting
- **Multiple output formats**: Table, JSON, YAML, CSV, and value formats
- **Google Cloud authentication**: Integrated OAuth 2.0 flow with credential management
- **Comprehensive cluster management**: Create, list, describe, update, and delete clusters
- **NodePool operations**: Full CRUD operations for cluster nodepools
- **Rich status information**: Detailed cluster and nodepool status with conditions
- **Configuration management**: Flexible configuration with profiles and defaults
- **Extensive testing**: Comprehensive unit and integration test coverage

## Installation

### From PyPI (Recommended)

```bash
pip install gcphcp
```

### From Source

```bash
git clone https://github.com/gcp-hcp/gcp-hcp-cli.git
cd gcp-hcp-cli
pip install -e .
```

### Development Installation

```bash
git clone https://github.com/gcp-hcp/gcp-hcp-cli.git
cd gcp-hcp-cli
make install-dev
```

## Quick Start

### 1. Initialize Configuration

```bash
gcphcp config init
# Follow the prompts to set API endpoint and default project
```

### 2. Authenticate

```bash
gcphcp auth login
# Opens browser for OAuth 2.0 authentication
```

### 3. List Clusters

```bash
gcphcp clusters list
```

## Usage

> **Tip:** Use `--help` on any command to see all available options and flags:
> ```bash
> gcphcp --help
> gcphcp clusters --help
> ```

### Authentication

```bash
# Login with Google Cloud Platform
gcphcp auth login

# Check authentication status
gcphcp auth status

# Get current access token
gcphcp auth token

# Logout (remove stored credentials)
gcphcp auth logout
```

### Configuration

```bash
# Initialize configuration interactively
gcphcp config init

# Set configuration values
gcphcp config set api_endpoint https://api.example.com
gcphcp config set default_project my-project-id

# Set hypershift binary path (optional, if not in PATH)
gcphcp config set hypershift_binary /path/to/hypershift

# Get configuration values
gcphcp config get api_endpoint
gcphcp config list

# Show configuration file location
gcphcp config path
```

**Configuration Options:**
- `api_endpoint` - Backend API URL (default: https://api.gcphcp.example.com)
- `default_project` - Default GCP project ID
- `hypershift_binary` - Path to hypershift CLI (default: searches PATH)

**Environment Variables:**
- `HYPERSHIFT_BINARY` - Override hypershift binary path

### Cluster Management



```bash
# List all clusters
gcphcp clusters list

# List clusters with filtering
gcphcp clusters list --status Ready --limit 20

# Get detailed cluster status (with watch mode)
gcphcp clusters status my-cluster
gcphcp clusters status my-cluster --watch

# Delete a cluster
gcphcp clusters delete my-cluster
```

#### Creating Clusters

**Option 1: Automatic Infrastructure Setup (Recommended)**

The simplest way to create a cluster - automatically provisions all required infrastructure:

```bash
gcphcp clusters create my-cluster --project my-project --setup-infra --region us-central1
```

**Option 2: Pre-Provisioned Infrastructure**

For more control, provision infrastructure separately then create the cluster:

```bash
# Step 1: Create infrastructure (generates config files)
gcphcp infra create my-infra --project my-project --region us-central1

# Step 2: Create cluster using the generated config files
gcphcp clusters create my-cluster \
  --iam-config-file my-infra-iam-config.json \
  --signing-key-file my-infra-signing-key.pem \
  --infra-config-file my-infra-infra-config.json
```

> **Note:** Infrastructure IDs must be **15 characters or less**.

### NodePool Management

```bash
# List nodepools for a cluster
gcphcp nodepools list --cluster abc123def456

# Create a new nodepool
gcphcp nodepools create workers --cluster abc123def456 \
  --machine-type n1-standard-4 --node-count 3

# Describe a nodepool
gcphcp nodepools describe nodepool-id

# Update a nodepool
gcphcp nodepools update nodepool-id --node-count 5

# Delete a nodepool
gcphcp nodepools delete nodepool-id
```

### Output Formatting

The CLI supports multiple output formats, similar to gcloud:

```bash
# Table format (default)
gcphcp clusters list

# JSON format
gcphcp clusters list --format json

# YAML format
gcphcp clusters list --format yaml

# CSV format
gcphcp clusters list --format csv

# Value format (for scripting)
gcphcp clusters list --format value
```

### Global Options

All commands support these global options:

- `--config`: Path to configuration file
- `--api-endpoint`: Override API endpoint URL
- `--project`: Override default project
- `--format`: Output format (table, json, yaml, csv, value)
- `--verbose` / `-v`: Increase verbosity (can be repeated)
- `--quiet` / `-q`: Suppress non-essential output

## Configuration

The CLI uses a YAML configuration file located at `~/.gcphcp/config.yaml` by default.

### Example Configuration

```yaml
api_endpoint: https://api.gcphcp.example.com
default_project: my-gcp-project
credentials_path: ~/.gcphcp/credentials.json

# Optional: OAuth client secrets for custom authentication
client_secrets_path: ~/.gcphcp/client_secrets.json
```

### Configuration Options

| Setting | Description | Default |
|---------|-------------|---------|
| `api_endpoint` | GCP HCP API endpoint URL | Required |
| `default_project` | Default GCP project ID | None |
| `credentials_path` | Path to stored credentials | `~/.gcphcp/credentials.json` |
| `client_secrets_path` | Path to OAuth client secrets | None |

### Environment Variables

The CLI supports the following environment variables:

| Variable | Description | Priority |
|----------|-------------|----------|
| `GCPHCP_CONFIG_PATH` | Path to configuration file | CLI flag > env var > default |
| `GCPHCP_API_ENDPOINT` | API endpoint URL | CLI flag > env var > config file > default |

**Example:**

```bash
export GCPHCP_CONFIG_PATH=/path/to/custom/config.yaml
export GCPHCP_API_ENDPOINT=https://my-api.example.com
gcphcp clusters list
```

## Authentication

The CLI uses Google Cloud Platform OAuth 2.0 authentication with the following scopes:

- `openid`: OpenID Connect
- `email`: User email address
- `profile`: User profile information
- `https://www.googleapis.com/auth/cloud-platform`: Cloud Platform access

### Authentication Flow

1. Run `gcphcp auth login`
2. Browser opens to Google OAuth consent screen
3. Grant permissions to the application
4. Credentials are stored securely for future use
5. The user's email is automatically included in API requests

## Development

### Setup Development Environment

```bash
git clone https://github.com/gcp-hcp/gcp-hcp-cli.git
cd gcp-hcp-cli
make setup-dev
```

### Running Tests

```bash
# Run all tests
make test

# Run unit tests only
make test-unit

# Run integration tests only
make test-integration

# Run with coverage
pytest --cov=gcphcp
```

### Code Quality

```bash
# Format code
make format

# Run linting
make lint

# Type checking
mypy src
```

### Building and Publishing

```bash
# Build package
make build

# Publish to PyPI (requires credentials)
make publish
```

## API Compatibility

This CLI is designed to work with GCP HCP API v1. The following endpoints are supported:

- `GET /health` - Health check
- `GET /api/v1/clusters` - List clusters
- `POST /api/v1/clusters` - Create cluster
- `GET /api/v1/clusters/{id}` - Get cluster
- `PUT /api/v1/clusters/{id}` - Update cluster
- `DELETE /api/v1/clusters/{id}` - Delete cluster
- `GET /api/v1/clusters/{id}/status` - Get cluster status
- `GET /api/v1/nodepools` - List nodepools
- `POST /api/v1/nodepools` - Create nodepool
- `GET /api/v1/nodepools/{id}` - Get nodepool
- `PUT /api/v1/nodepools/{id}` - Update nodepool
- `DELETE /api/v1/nodepools/{id}` - Delete nodepool

## Contributing

We welcome contributions! Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Reporting Issues

Please report issues on the [GitHub issue tracker](https://github.com/gcp-hcp/gcp-hcp-cli/issues).

### Development Guidelines

1. Follow PEP 8 style guidelines
2. Write comprehensive tests for new features
3. Update documentation for user-facing changes
4. Use type hints for all new code
5. Follow semantic versioning for releases

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Support

- Documentation: [https://gcp-hcp-cli.readthedocs.io](https://gcp-hcp-cli.readthedocs.io)
- Issue tracker: [https://github.com/gcp-hcp/gcp-hcp-cli/issues](https://github.com/gcp-hcp/gcp-hcp-cli/issues)
- PyPI package: [https://pypi.org/project/gcphcp/](https://pypi.org/project/gcphcp/)

## Changelog

See [CHANGELOG.md](CHANGELOG.md) for a history of changes to this project.