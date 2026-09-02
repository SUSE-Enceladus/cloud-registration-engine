# Cloud PAYG: Registration Engine

The primary objective of the **Registration Engine** is to provide a seamless, zero-touch registration and compliance experience for Pay-As-You-Go (PAYG) Rancher Manager / SUSE deployments originating from a cloud marketplace.

By automating the credential exchange and state management between the cloud billing/metadata APIs and the update infrastructure, this engine ensures that the deployment remains fully compliant, registered, and connected without requiring manual intervention from the cluster administrator.

---

## Core Objectives

*   **Automated Infrastructure Registration**
    The Cloud PAYG deployment is automatically registered with the update infrastructure upon provisioning, utilizing natively injected cloud identity credentials (e.g., Azure Workload Identity).

*   **Silent Periodic Verification**
    Built-in periodic registration verifications are automatically authenticated against the update infrastructure using the cryptographic state maintained by this engine's continuous loop.

*   **Frictionless User Experience**
    The end-user is never presented with a UI banner or request to manually register the product. The entire compliance lifecycle is handled completely transparently in the background.

---

## Architecture & Detailed Workflow

The Registration Engine runs as the `PID 1` process inside the container. It executes a continuous event loop with a base interval of **18 hours (64,800 seconds)**, modified by a randomized sleep jitter of **&plusmn;1 hour (3,600 seconds)** to prevent API stampedes across large clusters.

```
+-------------------------------------------------------------+
|               18-Hour Event Loop Execution                  |
+-------------------------------------------------------------+
                              |
                              v
             +----------------------------------+
             | Phase 1: Cloud Provider Detect  |
             | (Azure IMDS -> GCP IMDS -> AWS)  |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             | Phase 2: Metadata Collection     |
             | (Token Exchange & Attestation)   |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             | Phase 3: Configuration Loading   |
             | (Parse /etc/regionserverclnt.cfg)|
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             | Phase 4: SMT Discovery & Select  |
             | (Query, Health Check & SSL Cert) |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             | Phase 5: Happy Eyeballs Routing  |
             | (Establish preferred IP race)    |
             +----------------------------------+
                              |
                              v
             +----------------------------------+
             | Phase 6: Kubernetes Storage     |
             | (Patch/Create scc-registration)  |
             +----------------------------------+
```

### Execution Phases

#### 1. Cloud Provider Detection
The engine determines the host environment through a robust sequential fallback mechanism:
1.  **IMDS Queries:** Attempts to reach instance metadata endpoints with a strict 2-second timeout to prevent hanging on on-premise deployments:
    *   **Microsoft Azure IMDS:** Queries `169.254.169.254` and `[::ffff:169.254.169.254]`.
    *   **Google Cloud Platform IMDS:** Queries `metadata.google.internal` and IPv4/IPv6 IPs.
    *   **Amazon Web Services IMDS:** Queries `169.254.169.254` and `[fd00:ec2::254]` (checks IMDSv2 first, falling back to IMDSv1).
2.  **DMI Files Check:** Evaluates system-level files `/sys/class/dmi/id/{sys_vendor,product_name,chassis_asset_tag}` (can be overridden via `DMI_DIR_PATH` for local mock testing).
3.  **DMIDecode Fallback:** Runs the subprocess `dmidecode -s system-manufacturer` (gracefully handles permission/execution errors).

#### 2. Identity Verification & Cryptographic Attestation
*(Currently fully supported on Microsoft Azure)*
*   **ARM Identity Bootstrap:** Leverages Kubernetes-injected Workload Identity credentials to request a Bearer token for Azure Resource Manager (`https://management.azure.com/.default`).
*   **Plan Retrieval:** Obtains the extension deployment plan via ARM to resolve the authoritative publisher, offer, and plan ID for the running environment. The engine fails-closed immediately on retrieval errors.
*   **Cryptographic Attestation (IMDS):** Hashes the verified plan URN with SHA-3-256 to generate a 32-character base64-encoded nonce, queries the IMDS attested endpoint (`/metadata/attested/document`) to obtain a PKCS7 signature of the host, and packages it into an XML structure. Bypasses all system proxies during IMDS calls.

#### 3. Configuration Loading
Loads SMT server details and parameters from an INI file located at `/etc/regionserverclnt.cfg` (standard SLES config).

#### 4. SMT Server Discovery & Validation
Queries external region servers using the `cloudregister` library to list active update servers, checks responsiveness using fast-fail timeouts, and fetches and validates the SMT SSL certificate.

#### 5. Network Routing (Happy Eyeballs)
Initiates a TCP connection race (Happy Eyeballs) between the resolved SMT IPv4 and IPv6 addresses to determine the preferred routing IP.

#### 6. Kubernetes State Persistence
Under a Kubernetes environment, the compiled credentials and routing parameters are written directly to a Kubernetes secret (by default, `scc-registration` in the `cattle-scc-system` namespace) using the Kubernetes REST API. It retries automatically with exponential backoff on transient errors.

---

## Technical Specifications & Prerequisites

*   **Base Image:** SUSE Linux Enterprise Server (SLES) 15 SP7.
*   **Runtime:** Python 3.11 (*STRICT constraint: No Python 3.12+ features allowed*).
*   **Ecosystem Tooling:** Poetry for dependency management, Ruff/flake8 for linting/formatting, pytest for testing.
*   **OS zypper Packages Required:**
    *   `python311`
    *   `regionServiceClientConfigAzure`
    *   `cloud-regionsrv-client`
    *   `cloud-regionsrv-client-plugin-azure`
    *   `regionServiceCertsAzure`
    *   `regionsrv-certs`
    *   `ca-certificates`
    *   `ca-certificates-mozilla`

---

## Environment Variables Reference

| Variable | Description | Default Value | Required For |
| :--- | :--- | :--- | :--- |
| **Azure Workload Identity** | | | |
| `AZURE_CLIENT_ID` | Client ID of the Managed Application identity. | *(Injected by K8s webhook)* | Azure ARM Calls |
| `AZURE_TENANT_ID` | Tenant ID of the Azure AD Tenant. | *(Injected by K8s webhook)* | Azure ARM Calls |
| `AZURE_FEDERATED_TOKEN_FILE`| Path to the federated JWT token injected by K8s. | *(Injected by K8s webhook)* | Azure ARM Calls |
| `EXTENSION_RESOURCE_ID` | Resource ID of the extension to verify. | *None* | Plan Verification |
| **Kubernetes Storage** | | | |
| `REGISTRATION_SECRET_NAME` | The Kubernetes secret name to save credentials. | `scc-registration` | Kubernetes State |
| `REGISTRATION_SECRET_NAMESPACE` | The Kubernetes namespace for the secret. | `cattle-scc-system` | Kubernetes State |
| `REG_CODE` / `REG_CODE` / `REGCODE`| The active SUSE/Rancher registration code. | *None* | Kubernetes State |
| `KUBERNETES_SERVICE_HOST` | Host IP address of the Kubernetes API Server. | *(Injected by K8s)* | Kubernetes State |
| `KUBERNETES_SERVICE_PORT` | Port of the Kubernetes API Server. | *(Injected by K8s)* | Kubernetes State |
| `KUBERNETES_TOKEN` | Bearer token to authorize against K8s API. | `/var/run/secrets/.../token` | Kubernetes State (fallback) |
| `KUBERNETES_CA_CERT` | Path to Kubernetes CA cert or `"False"` to ignore.| `/var/run/secrets/.../ca.crt` | Kubernetes State (fallback) |
| **Application & Retries** | | | |
| `REGISTRATION_ENGINE_LOG_LEVEL` | Dynamic log level during execution (takes precedence). Supports DEBUG, INFO, WARNING, ERROR, CRITICAL. | `INFO` | Logger Configuration |
| `LOG_LEVEL` | Dynamic log level during execution fallback. Supports DEBUG, INFO, WARNING, ERROR, CRITICAL. | `INFO` | Logger Configuration |
| `VERIFY_RETRY_MAX` | Max retries for Azure ARM token & plan verification. | `5` | Azure ARM Calls |
| `VERIFY_RETRY_BACKOFF` | Exponential retry backoff multiplier for ARM calls. | `2.0` | Azure ARM Calls |
| `K8S_RETRY_MAX` | Max retries for Kubernetes secret read/write calls. | `5` | Kubernetes State |
| `K8S_RETRY_BACKOFF` | Exponential retry backoff multiplier for K8s calls. | `2.0` | Kubernetes State |
| `DMI_DIR_PATH` | Path override for `/sys/class/dmi/id/` files. | `/sys/class/dmi/id` | Local/Mock Testing |

---

## Configuration File Reference (`/etc/regionserverclnt.cfg`)

The SMT discovery requires an INI-format configuration file. Ensure it is mounted or provisioned exactly as follows:

```ini
[server]
api = regionInfo
certLocation = /usr/lib/regionService/certs
regionsrv = 0:0:0:0

[instance]
dataProvider = /usr/bin/azuremetadata --api latest
instanceArgs = msftazure
httpsOnly = true
```

---

## Usage & Development Examples

### 1. Local Development & Testing

#### Dependencies Installation
Ensure you have [Poetry](https://python-poetry.org/) installed, and run:
```bash
poetry install
```

#### Running the Registration Engine
To run the continuous registration engine event loop locally:
```bash
poetry run registration-engine
```

#### Mocking Cloud Providers Locally
To test the cloud detection fallback behavior on non-cloud hardware, configure custom DMI path overlays using `DMI_DIR_PATH`:
```bash
# To mock a Microsoft Azure environment
export DMI_DIR_PATH="tests/data/dmi/azure"
poetry run registration-engine
```

#### Running the Test Suite
The test suite utilizes mocks extensively to prevent any live network queries to Azure, IMDS, or Kubernetes. Run tests using pytest:
```bash
poetry run pytest
```

---

### 2. Kubernetes Deployment Configuration

To run the Registration Engine in a Kubernetes environment under least-privilege policies, deploy the following manifests:

#### ServiceAccount & Role Configurations
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: marketplace-verify-sa
  namespace: cattle-scc-system
  annotations:
    # Enabled Azure Workload Identity mutating webhook support
    azure.workload.identity/client-id: "00000000-0000-0000-0000-000000000000"
    azure.workload.identity/tenant-id: "00000000-0000-0000-0000-000000000000"
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: registration-secret-manager
  namespace: cattle-scc-system
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    resourceNames: ["scc-registration"]
    verbs: ["get", "create", "update", "patch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: registration-secret-manager-binding
  namespace: cattle-scc-system
subjects:
  - kind: ServiceAccount
    name: marketplace-verify-sa
    namespace: cattle-scc-system
roleRef:
  kind: Role
  name: registration-secret-manager
  apiGroup: rbac.authorization.k8s.io
```

#### Mounting SMT Configuration via ConfigMap
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: regionserverclnt-config
  namespace: cattle-scc-system
data:
  regionserverclnt.cfg: |
    [server]
    api = regionInfo
    certLocation = /usr/lib/regionService/certs
    regionsrv = 0:0:0:0

    [instance]
    dataProvider = /usr/bin/azuremetadata --api latest
    instanceArgs = msftazure
    httpsOnly = true
```

#### Deployment Manifest
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: registration-engine
  namespace: cattle-scc-system
  labels:
    app: registration-engine
    azure.workload.identity/use: "true" # Triggers Azure Workload Identity token injection
spec:
  replicas: 1
  selector:
    matchLabels:
      app: registration-engine
  template:
    metadata:
      labels:
        app: registration-engine
        azure.workload.identity/use: "true"
    spec:
      serviceAccountName: marketplace-verify-sa
      containers:
        - name: registration-engine
          image: registration-engine:latest
          imagePullPolicy: IfNotPresent
          env:
            - name: REGISTRATION_CODE
              value: "SUSE-REGISTRATION-CODE-HERE"
            - name: EXTENSION_RESOURCE_ID
              value: "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/my-rg/providers/Microsoft.Compute/virtualMachines/my-vm/extensions/RancherPAYG"
          volumeMounts:
            - name: config-volume
              mountPath: /etc/regionserverclnt.cfg
              subPath: regionserverclnt.cfg
      volumes:
        - name: config-volume
          configMap:
            name: regionserverclnt-config
```
