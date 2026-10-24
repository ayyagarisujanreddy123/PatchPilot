<?php
declare(strict_types=1);

// Executed with php -n as a different UID from the app. No application includes.
ini_set('display_errors', '0');
$budget = max(1, min(85, (int) ($argv[1] ?? 60)));
$deadline = hrtime(true) / 1e9 + $budget;
$manifest = json_decode(file_get_contents('/sandbox/manifest.json'), true, 16, JSON_THROW_ON_ERROR);

function remaining(): float {
    global $deadline;
    $left = $deadline - hrtime(true) / 1e9;
    if ($left <= 0) { throw new RuntimeException('HTTP deadline exceeded'); }
    return min(8.0, $left);
}

function request(string $method, string $path, string $body = '', string $contentType = ''): array {
    $start = hrtime(true);
    $socket = @stream_socket_client('tcp://127.0.0.1:8080', $errno, $error, remaining(), STREAM_CLIENT_CONNECT);
    if ($socket === false) { throw new RuntimeException('No HTTP connection'); }
    try {
        $headers = "$method $path HTTP/1.0\r\nHost: localhost\r\nAccept: application/json\r\nAccept-Encoding: identity\r\nConnection: close\r\n";
        if ($method === 'POST') { $headers .= 'Content-Type: ' . $contentType . "\r\nContent-Length: " . strlen($body) . "\r\n"; }
        $outgoing = $headers . "\r\n" . $body;
        for ($offset = 0; $offset < strlen($outgoing);) {
            $timeout = remaining();
            stream_set_timeout($socket, (int) $timeout, (int) (($timeout - floor($timeout)) * 1e6));
            $written = @fwrite($socket, substr($outgoing, $offset, 65536));
            if ($written === false || $written === 0) { throw new RuntimeException('HTTP write failed'); }
            $offset += $written;
        }
        $received = '';
        for ($reads = 0; !feof($socket); $reads++) {
            if ($reads > 4096 || strlen($received) > 540672) { throw new RuntimeException('HTTP response exceeded limit'); }
            $timeout = remaining();
            stream_set_timeout($socket, (int) $timeout, (int) (($timeout - floor($timeout)) * 1e6));
            $part = @fread($socket, 16384);
            if ($part === false || ($part === '' && !feof($socket))) { throw new RuntimeException('HTTP read failed'); }
            $received .= $part;
        }
        $split = strpos($received, "\r\n\r\n");
        if ($split === false || $split > 16384) { throw new RuntimeException('HTTP headers exceeded limit'); }
        $head = substr($received, 0, $split);
        if (!preg_match('/^HTTP\/1\.[01] ([1-5][0-9]{2})(?: |\r|$)/', $head, $match)) { throw new RuntimeException('Invalid HTTP status'); }
        $body = substr($received, $split + 4);
        if (strlen($body) > 524288) { throw new RuntimeException('HTTP body exceeded limit'); }
        $json = json_decode($body, true, 32);
        return ['status' => (int) $match[1], 'json' => is_array($json) ? $json : [],
            'banner_hidden' => preg_match('/\r\nx-powered-by\s*:/i', $head) !== 1,
            'duration_ms' => (int) round((hrtime(true) - $start) / 1e6)];
    } finally { fclose($socket); }
}

function business(string $method, string $path, string $body = '', string $contentType = ''): array {
    $start = hrtime(true);
    try { return request($method, $path, $body, $contentType); }
    catch (Throwable $error) { return ['status' => 0, 'json' => [], 'banner_hidden' => false, 'duration_ms' => min(90000, (int) round((hrtime(true) - $start) / 1e6))]; }
}

try {
    $readyUntil = min($deadline, hrtime(true) / 1e9 + 8);
    do {
        try { $runtime = request('GET', '/.well-known/patchpilot-sandbox-runtime'); break; }
        catch (Throwable $error) {
            if (hrtime(true) / 1e9 >= $readyUntil) { throw new RuntimeException('Runtime unavailable'); }
            usleep(100000);
        }
    } while (true);
    if ($runtime['status'] !== 200 || !isset($runtime['json']['runtime'], $runtime['json']['identity'])) { throw new RuntimeException('Invalid runtime observation'); }
    $observations = ['banner_hidden' => $runtime['banner_hidden']];
    $durations = ['runtime' => $runtime['duration_ms']];
    $home = business('GET', '/');
    $observations['homepage_status'] = $home['status'];
    $durations['homepage'] = $home['duration_ms'];
    $observations['banner_hidden'] = $observations['banner_hidden'] && $home['banner_hidden'];
    if (in_array('contact', $manifest['capabilities'], true)) {
        foreach ([true, false] as $valid) {
            $key = $valid ? 'contact_valid' : 'contact_invalid';
            $fields = $valid ? ['name' => 'PatchPilot Check', 'email' => 'verification@example.invalid', 'message' => 'Fixed sandbox behavior verification.']
                : ['name' => '', 'email' => 'invalid-email', 'message' => ''];
            $response = business('POST', $manifest['contact'], http_build_query($fields), 'application/x-www-form-urlencoded');
            $json = $response['json'];
            $errors = $json['errors'] ?? null;
            $observations[$key] = ['status' => $response['status'], 'valid' => isset($json['valid']) && is_bool($json['valid']) ? $json['valid'] : null];
            if ($valid) { $observations[$key]['errors_empty'] = is_array($errors) && count($errors) === 0; }
            else { $observations[$key]['required_errors'] = is_array($errors) && isset($errors['name'], $errors['email'], $errors['message'])
                && is_string($errors['name']) && $errors['name'] !== '' && is_string($errors['email']) && $errors['email'] !== '' && is_string($errors['message']) && $errors['message'] !== ''; }
            $durations[$key] = $response['duration_ms'];
        }
    }
    if (in_array('upload', $manifest['capabilities'], true)) {
        $payload = random_bytes(3145728);
        $boundary = 'patchpilot-' . bin2hex(random_bytes(16));
        $body = '--' . $boundary . "\r\nContent-Disposition: form-data; name=\"document\"; filename=\"verification.bin\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            . $payload . "\r\n--" . $boundary . "--\r\n";
        $response = business('POST', $manifest['upload'], $body, 'multipart/form-data; boundary=' . $boundary);
        $json = $response['json'];
        $expectedHash = hash('sha256', $payload);
        $receivedHash = isset($json['sha256']) && is_string($json['sha256']) && preg_match('/^[0-9a-f]{64}$/D', $json['sha256']) === 1 ? $json['sha256'] : null;
        $observations['upload'] = ['status' => $response['status'], 'expected_bytes' => 3145728,
            'bytes_received' => isset($json['bytes_received']) && is_int($json['bytes_received']) ? $json['bytes_received'] : null,
            'expected_sha256' => $expectedHash, 'sha256' => $receivedHash,
            'sha256_matches' => ($json['status'] ?? '') === 'success' && $receivedHash !== null && hash_equals($expectedHash, $receivedHash)];
        $durations['upload'] = $response['duration_ms'];
    }
    echo json_encode(['runtime' => $runtime['json']['runtime'], 'identity' => $runtime['json']['identity'],
        'observations' => $observations, 'durations_ms' => $durations], JSON_THROW_ON_ERROR);
} catch (Throwable $error) {
    // Never print response bodies, server errors, paths, or exception messages.
    fwrite(STDERR, "Trusted sandbox HTTP verification could not complete.\n");
    exit(2);
}
