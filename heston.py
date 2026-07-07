"""
Heston stochastic-volatility pricer.

Pure Python, standard library only (cmath plus a self-contained Gauss-Legendre
quadrature over the model's characteristic function), mirroring pricing_engine.py.
It uses the numerically stable "little Heston trap" formulation (Albrecher, Mayer,
Schoutens & Tistaert 2007), so long-dated (LEAPS) prices stay stable where the
original Heston 1993 branch choice can jump.

Risk-neutral dynamics:
    dS = (r - q) S dt + sqrt(v) S dW1
    dv = kappa (theta - v) dt + xi sqrt(v) dW2,     dW1 dW2 = rho dt

Parameters (all variance-space, i.e. vol squared):
    v0     initial variance
    kappa  mean-reversion speed
    theta  long-run variance
    xi     vol of vol
    rho    spot / vol correlation (negative for equity skew)

Price via the two Heston probabilities:
    Call = S e^{-qT} P1 - K e^{-rT} P2,   Put by put-call parity.
"""
import cmath
import math


def _gauss_legendre(n):
    """Nodes and weights of the n-point Gauss-Legendre rule on [-1, 1].

    Roots of the Legendre polynomial P_n found by Newton's method, using the
    three-term recurrence to evaluate P_n and its derivative. Standard, and
    dependency-free so the pricer needs nothing beyond the standard library.
    """
    nodes = [0.0] * n
    weights = [0.0] * n
    m = (n + 1) // 2
    for i in range(m):
        x = math.cos(math.pi * (i + 0.75) / (n + 0.5))  # initial guess for root i
        dp = 1.0
        for _ in range(100):
            p_prev, p_curr = 1.0, x          # P_0, P_1
            for k in range(2, n + 1):
                p_prev, p_curr = p_curr, ((2 * k - 1) * x * p_curr - (k - 1) * p_prev) / k
            dp = n * (x * p_curr - p_prev) / (x * x - 1.0)  # P_n'(x)
            dx = p_curr / dp
            x -= dx
            if abs(dx) < 1e-15:
                break
        nodes[i] = -x
        nodes[n - 1 - i] = x
        w = 2.0 / ((1.0 - x * x) * dp * dp)
        weights[i] = w
        weights[n - 1 - i] = w
    return nodes, weights


_GL_N = 128
_GL_NODES, _GL_WEIGHTS = _gauss_legendre(_GL_N)
_U_MAX = 200.0  # upper truncation of the semi-infinite Fourier integral


def _char_func(phi, j, x, T, r, q, v0, kappa, theta, xi, rho):
    """Heston characteristic function f_j(phi), little-trap form. x = ln(S)."""
    if j == 1:
        u = 0.5
        b = kappa - rho * xi
    else:
        u = -0.5
        b = kappa
    rsp = rho * xi * phi * 1j
    d = cmath.sqrt((rsp - b) ** 2 - xi * xi * (2.0 * u * phi * 1j - phi * phi))
    g = (b - rsp - d) / (b - rsp + d)          # little trap: minus d in numerator
    e_dt = cmath.exp(-d * T)
    C = ((r - q) * phi * 1j * T
         + (kappa * theta / (xi * xi))
         * ((b - rsp - d) * T - 2.0 * cmath.log((1.0 - g * e_dt) / (1.0 - g))))
    D = ((b - rsp - d) / (xi * xi)) * ((1.0 - e_dt) / (1.0 - g * e_dt))
    return cmath.exp(C + D * v0 + 1j * phi * x)


def _prob(j, S, K, T, r, q, v0, kappa, theta, xi, rho, nodes, weights):
    """Heston probability P_j via Gauss-Legendre quadrature over [0, U_MAX]."""
    x = math.log(S)
    ln_k = math.log(K)
    half = _U_MAX / 2.0
    total = 0.0
    for node, w in zip(nodes, weights):
        phi = half * (node + 1.0)  # map [-1, 1] -> [0, U_MAX]
        f = _char_func(phi, j, x, T, r, q, v0, kappa, theta, xi, rho)
        total += w * (cmath.exp(-1j * phi * ln_k) * f / (1j * phi)).real
    return 0.5 + (half * total) / math.pi


def heston_price(S, K, T, r, v0, kappa, theta, xi, rho,
                 option_type="call", q=0.0, gl_n=None):
    """Price a European option under Heston. gl_n overrides the quadrature order."""
    otype = option_type.lower()
    if T <= 0:
        intrinsic = (S - K) if otype == "call" else (K - S)
        return max(0.0, intrinsic)
    if xi <= 0:
        xi = 1e-6  # keep the characteristic function finite; calibration bounds xi away from 0

    if gl_n in (None, _GL_N):
        nodes, weights = _GL_NODES, _GL_WEIGHTS
    else:
        nodes, weights = _gauss_legendre(gl_n)

    p1 = _prob(1, S, K, T, r, q, v0, kappa, theta, xi, rho, nodes, weights)
    p2 = _prob(2, S, K, T, r, q, v0, kappa, theta, xi, rho, nodes, weights)
    call = S * math.exp(-q * T) * p1 - K * math.exp(-r * T) * p2
    # Clamp tiny negative numerical noise for deep out-of-the-money calls.
    call = max(call, 0.0)
    if otype == "call":
        return call
    return call - S * math.exp(-q * T) + K * math.exp(-r * T)


def feller_ok(kappa, theta, xi):
    """Feller condition 2*kappa*theta >= xi^2 keeps variance strictly positive."""
    return 2.0 * kappa * theta >= xi * xi
