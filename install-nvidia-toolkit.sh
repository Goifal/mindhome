#!/bin/bash
# NVIDIA Container Toolkit Installation
set -e

echo "=== Schritt 1: Repository-Liste hinzufuegen ==="
curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

echo ""
echo "=== Schritt 2: Installieren ==="
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit

echo ""
echo "=== Schritt 3: Docker Runtime konfigurieren ==="
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

echo ""
echo "=== Schritt 4: Test ==="
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu24.04 nvidia-smi

echo ""
echo "=== Fertig! GPU ist bereit fuer Docker ==="
