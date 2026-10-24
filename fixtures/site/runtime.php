<?php
header('Content-Type: application/json; charset=utf-8');

$deploymentId = getenv('DEPLOYMENT_ID') ?: 'unspecified';
$siteId = getenv('SITE_ID') ?: 'unspecified';
$orgName = getenv('ORG_NAME') ?: 'PatchPilot Fixture';

$runtimeInfo = [
    'status' => 'ok',
    'php_version' => PHP_VERSION,
    'php_sapi' => php_sapi_name(),
    'deployment_id' => $deploymentId,
    'site_id' => $siteId,
    'organization' => $orgName,
    'session_upload_progress_enabled' => (bool) ini_get('session.upload_progress.enabled'),
    'upload_max_filesize' => ini_get('upload_max_filesize'),
    'post_max_size' => ini_get('post_max_size'),
    'server_software' => $_SERVER['SERVER_SOFTWARE'] ?? 'unknown',
];

echo json_encode($runtimeInfo, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES);
