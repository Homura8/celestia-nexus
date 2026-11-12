# ios-qemu / iPhone X iOS 16.7.16

Implemented recipe: `ios-qemu`. Reproduces lgrachov/ios-qemu's stock-userland
boot; guide and limits in [docs/ios-qemu.md](../../docs/ios-qemu.md).

| Component | Input / result |
| --- | --- |
| Kernel | ios-qemu CI artifact (run 40196425620): XNU 8796.141.3 + patches 0001–0108, SHA pinned; patch tree checked against the pinned source |
| Loader | upstream's 6-instruction stub + generated Apple device tree (D22AP `/product` from your IPSW) |
| Userland | unmodified iPhone X iOS 16.7.16 (20H392) OS + SystemOS + AppOS from **your** IPSW, on journaled HFS+ over emulated UFS |
| Machine | QEMU `virt`, GICv3, `-accel hvf -cpu host`, 4 vCPUs, 7 GiB, ramfb/virtio input/net |
| Host | macOS on Apple Silicon only; verified on M1 Pro / macOS 27.2.1 / QEMU 11.1.3 |
| Verified endpoint | kernel → root → launchd → backboardd + SpringBoard → GUI on screen → injected unlock + tap starts Safari |

```sh
T="--target ios-qemu-iphonex"
./nexus $T doctor
./nexus $T fetch && ./nexus $T build
./nexus $T prepare-disk --ipsw /path/to/iPhone10,3,iPhone10,6_16.7.16_20H392_Restore.ipsw
./nexus $T run
```

Nothing derived from the IPSW leaves `.nexus/`. Not a usable or secure device:
no GPU, Secure Enclave or code-signing security; see the guide.
