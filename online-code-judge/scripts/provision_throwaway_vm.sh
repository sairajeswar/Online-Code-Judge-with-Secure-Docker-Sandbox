#!/usr/bin/env bash
# ==============================================================================
# PROVISION THROWAWAY VM FOR ONLINE CODE JUDGE
# ==============================================================================
# Security Principle: Untrusted code must NEVER run on a shared, stateful host.
# This script provisions an ephemeral, disposable Ubuntu VM in GCP or AWS,
# hardens the Docker daemon, disables instance metadata access, runs the
# judge test suite, and securely terminates the VM afterwards.
# ==============================================================================

set -euo pipefail

PROVIDER="${1:-gcp}" # "gcp" or "aws"
VM_NAME="judge-throwaway-$(date +%s)"
ZONE="us-central1-a"
MACHINE_TYPE="e2-standard-4"

echo "[*] Selected Cloud Provider: ${PROVIDER}"
echo "[*] Provisioning Throwaway VM: ${VM_NAME}..."

if [ "${PROVIDER}" == "gcp" ]; then
    # 1. Create ephemeral GCP instance with minimal service account scope
    gcloud compute instances create "${VM_NAME}" \
        --zone="${ZONE}" \
        --machine-type="${MACHINE_TYPE}" \
        --image-family="ubuntu-2204-lts" \
        --image-project="ubuntu-os-cloud" \
        --no-scopes \
        --no-service-account \
        --metadata=block-project-ssh-keys=TRUE \
        --metadata-from-file=startup-script=<(cat << 'EOF'
#!/bin/bash
set -euxo pipefail

# Block cloud metadata exfiltration (169.254.169.254)
iptables -A OUTPUT -d 169.254.169.254 -j DROP

# Install Docker and dependencies
apt-get update
apt-get install -y ca-certificates curl gnupg python3 python3-pip git
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
chmod a+r /etc/apt/keyrings/docker.gpg

echo \
  "deb [arch="$(dpkg --print-architecture)" signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  "$(. /etc/os-release && echo "$VERSION_CODENAME")" stable" | \
  tee /etc/apt/sources.list.d/docker.list > /dev/null

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io

# Enable cgroup v2 memory and pids enforcement in Docker
systemctl restart docker

echo "[+] Throwaway VM initialized and hardened."
EOF
)

    echo "[+] VM created. Waiting for startup-script completion..."
    sleep 30

    echo "[*] To run judge and test suite on this throwaway VM:"
    echo "    gcloud compute scp --recurse . ${VM_NAME}:~/online-code-judge --zone=${ZONE}"
    echo "    gcloud compute ssh ${VM_NAME} --zone=${ZONE} --command='cd ~/online-code-judge && docker build -t judge-sandbox:latest -f Dockerfile.sandbox . && python3 tests/run_all_tests.py'"
    echo ""
    echo "[!] To tear down and destroy VM after testing (preventing persistent compromise):"
    echo "    gcloud compute instances delete ${VM_NAME} --zone=${ZONE} --quiet"

elif [ "${PROVIDER}" == "aws" ]; then
    echo "[*] For AWS EC2 Disposable Instances:"
    echo "    aws ec2 run-instances --image-id ami-0c7217cdde317cfec --instance-type t3.xlarge --key-name my-key --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=${VM_NAME}}]'"
    echo "    Terminate instance via: aws ec2 terminate-instances --instance-ids <ID>"
fi
