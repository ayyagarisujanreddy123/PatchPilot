<?php
declare(strict_types=1);

// This router is trusted, immutable and outside the repository document root.
if (parse_url($_SERVER['REQUEST_URI'] ?? '', PHP_URL_PATH) === '/.well-known/patchpilot-sandbox-runtime') {
    $manifest = json_decode(file_get_contents('/sandbox/manifest.json'), true, 16, JSON_THROW_ON_ERROR);
    $runtime = ['php_version' => PHP_VERSION];
    foreach (['display_errors', 'display_startup_errors', 'log_errors', 'expose_php'] as $key) {
        $raw = strtolower(trim((string) ini_get($key)));
        $runtime[$key] = match ($raw) {
            '', '0', 'off', 'no', 'false' => false,
            '1', 'on', 'yes', 'true', 'stderr', 'stdout' => true,
            default => null,
        };
    }
    header('Content-Type: application/json');
    echo json_encode(['runtime' => $runtime, 'identity' => [
        'sapi' => PHP_SAPI, 'site_id' => $manifest['site_id'], 'phase' => $manifest['phase'],
    ]], JSON_THROW_ON_ERROR);
    return true;
}
return false;
