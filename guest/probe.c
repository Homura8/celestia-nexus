/* SPDX-License-Identifier: MIT
 * Freestanding Darwin/AArch64 PID 1. No SDK, libc, dyld, or Apple binaries.
 * Syscall numbers: apple-oss-distributions/xnu, xnu-8796.121.2,
 * bsd/kern/syscalls.master. ABI: bsd/dev/arm/systemcalls.c.
 */
typedef unsigned long usize;
struct result { long value; unsigned error; };

/* Clang may lower zero-initialized stack buffers to bzero even freestanding. */
void bzero(void *pointer, usize count)
{
    volatile unsigned char *bytes = pointer;
    while (count--) *bytes++ = 0;
}

static struct result call(long number, long a, long b, long c, long d, long e, long f)
{
    register long r0 __asm__("x0") = a;
    register long r1 __asm__("x1") = b;
    register long r2 __asm__("x2") = c;
    register long r3 __asm__("x3") = d;
    register long r4 __asm__("x4") = e;
    register long r5 __asm__("x5") = f;
    register long r16 __asm__("x16") = number;
    unsigned error;
    __asm__ volatile("svc #0x80\n\tcset %w[error], cs"
        : "+r"(r0), "+r"(r1), "+r"(r2), "+r"(r3), "+r"(r4), "+r"(r5),
          "+r"(r16), [error] "=r"(error) : : "memory", "cc");
    return (struct result){r0, error};
}

static usize length(const char *s)
{
    usize n = 0;
    while (s[n]) ++n;
    return n;
}

static int console;
static int failures;

static void text(const char *s)
{
    usize n = length(s);
    while (n) {
        struct result r = call(4, console, (long)s, n, 0, 0, 0);
        if (r.error || r.value <= 0) return;
        s += r.value;
        n -= (usize)r.value;
    }
}

static void check(const char *name, int pass)
{
    text("NEXUS CHECK "); text(name); text(pass ? " PASS\n" : " FAIL\n");
    if (!pass) ++failures;
}

static int wait(void)
{
    long timeout[2] = {1, 0};
    struct result slept = call(93, 0, 0, 0, 0, (long)timeout, 0); /* select, one second */
    return !slept.error && slept.value == 0;
}

/* An unpredictable host-generated token must travel through boot_args and sysctl.
 * Matching a static success string in a loader or an old log cannot pass a run.
 */
static char token[33];
static void boot_token(void)
{
    char args[1024] = {0};
    usize n = sizeof(args);
    struct result r = call(274, (long)"kern.bootargs", 13, (long)args, (long)&n, 0, 0);
    int found = 0;
    if (!r.error && r.value == 0 && n < sizeof(args)) {
        const char *key = "nexus_token=";
        for (usize i = 0; args[i]; ++i) {
            if (i && args[i-1] != ' ') continue;
            usize j = 0;
            while (key[j] && args[i+j] == key[j]) ++j;
            if (key[j]) continue;
            usize k = 0;
            while (k < 32) {
                char c = args[i+j+k];
                if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) break;
                token[k++] = c;
            }
            found = k == 32 && (args[i+j+k] == ' ' || args[i+j+k] == 0);
            break;
        }
    }
    check("boot-token", found);
}

void start(void) __attribute__((noreturn));
void start(void)
{
    struct result opened = call(5, (long)"/dev/console", 2, 0, 0, 0, 0);
    console = opened.error ? 1 : (int)opened.value;
    text("\nNEXUS PROBE 1\n");
    check("console", !opened.error && opened.value >= 0);
    struct result pid = call(20, 0, 0, 0, 0, 0, 0);
    check("pid1", !pid.error && pid.value == 1);
    struct result uid = call(24, 0, 0, 0, 0, 0, 0);
    check("uid0", !uid.error && uid.value == 0);

    char version[512] = {0};
    usize version_size = sizeof(version);
    struct result sysctl = call(274, (long)"kern.version", 12, (long)version,
                               (long)&version_size, 0, 0);
    check("sysctl", !sysctl.error && sysctl.value == 0 && version_size > 1 && version_size < sizeof(version));
    if (!sysctl.error && version_size < sizeof(version)) {
        text("NEXUS KERNEL "); text(version); text("\n");
    }
    boot_token();

    struct result missing = call(5, (long)"/nexus-file-that-does-not-exist", 0, 0, 0, 0, 0);
    check("errno", missing.error && missing.value == 2); /* ENOENT and carry */

    struct result mapped = call(197, 0, 16384, 3, 0x1002, -1, 0); /* anonymous/private RW */
    int memory_ok = !mapped.error && mapped.value != 0 && mapped.value != -1;
    if (memory_ok) {
        volatile unsigned char *memory = (volatile unsigned char *)mapped.value;
        for (usize i = 0; i < 16384; ++i) memory[i] = (unsigned char)(i * 37 + 11);
        for (usize i = 0; i < 16384; ++i) {
            if (memory[i] != (unsigned char)(i * 37 + 11)) memory_ok = 0;
        }
    }
    check("mmap-rw", memory_ok);
    if (!mapped.error) {
        struct result protected = call(74, mapped.value, 16384, 1, 0, 0, 0);
        check("mprotect", !protected.error && protected.value == 0);
        struct result unmapped = call(73, mapped.value, 16384, 0, 0, 0, 0);
        check("munmap", !unmapped.error && unmapped.value == 0);
    } else {
        check("mprotect", 0); check("munmap", 0);
    }

    long before[2] = {0}, after[2] = {0};
    struct result t1 = call(116, (long)before, 0, 0, 0, 0, 0);
    int slept = wait();
    struct result t2 = call(116, (long)after, 0, 0, 0, 0, 0);
    check("timer", slept && !t1.error && !t2.error &&
          (after[0] - before[0]) * 1000000 + after[1] - before[1] >= 900000);

    text(failures ? "NEXUS RESULT FAIL token=" : "NEXUS RESULT PASS token=");
    text(token); text("\n");
    /* Exiting PID 1 panics XNU. Stay alive and demonstrate timer interrupts. */
    for (;;) {
        if (!wait()) check("heartbeat-wait", 0);
        text("NEXUS HEARTBEAT\n");
    }
}
