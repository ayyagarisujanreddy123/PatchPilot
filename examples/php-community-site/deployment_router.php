<?php
// Trusted deployment-only router. The generated identity is outside the Git tree.
$path = parse_url($_SERVER['REQUEST_URI'] ?? '/', PHP_URL_PATH);
if ($path === '/.well-known/patchpilot.json') {
    $method = $_SERVER['REQUEST_METHOD'] ?? 'GET';
    if ($method !== 'GET' && $method !== 'HEAD') {
        http_response_code(405);
        header('Allow: GET, HEAD');
        return true;
    }
    header('Content-Type: application/json; charset=utf-8');
    header('Cache-Control: no-store');
    if (!is_file('/deployment/marker.json')) {
        http_response_code(503);
        return true;
    }
    if ($method !== 'HEAD') {
        readfile('/deployment/marker.json');
    }
    return true;
}
return false;
