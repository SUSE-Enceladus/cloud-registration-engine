# Rancher PAYG: Registration Engine

The primary objective of the **Registration Engine** is to provide a seamless, zero-touch registration and compliance experience for Rancher Manager Pay-As-You-Go (PAYG) deployments originating from a cloud marketplace.

By automating the credential exchange and state management between Azure's billing APIs and the SUSE/Rancher ecosystem, this architecture ensures that the deployment remains fully compliant and connected without requiring manual intervention from the cluster administrator.

## Core Objectives

*   **Automated Infrastructure Registration**
    The Rancher Manager PAYG deployment is automatically registered with the SUSE update infrastructure upon provisioning, utilizing natively injected Azure Managed Application identities.

*   **Silent Periodic Verification**
    Rancher’s built-in periodic registration verifications are automatically authenticated against the update infrastructure using the cryptographic state maintained by this engine's 18-hour loop.

*   **Frictionless User Experience**
    The end-user is never presented with a UI banner or request to manually register the product. The entire compliance lifecycle is handled completely transparently in the background.
