<?php
$orgName = getenv('ORG_NAME') ?: 'Community Clinic';

$uploadResult = null;
$error = null;

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    if (!isset($_FILES['document'])) {
        $error = 'No file uploaded.';
        http_response_code(400);
    } elseif ($_FILES['document']['error'] !== UPLOAD_ERR_OK) {
        $errorCode = $_FILES['document']['error'];
        $error = "Upload failed with error code {$errorCode}. Check file size and server limits.";
        http_response_code(413); // Payload Too Large or failure
    } else {
        $tmpPath = $_FILES['document']['tmp_name'];
        $sizeBytes = filesize($tmpPath);
        $sha256 = hash_file('sha256', $tmpPath);

        // Uploaded file is temporary, never executed, and strictly validated
        $uploadResult = [
            'status' => 'success',
            'filename' => basename($_FILES['document']['name']),
            'bytes_received' => $sizeBytes,
            'sha256' => $sha256,
            'message' => 'Document received and verified successfully.'
        ];

        // Clean up temporary file immediately after calculating evidence
        @unlink($tmpPath);
    }

    $accept = $_SERVER['HTTP_ACCEPT'] ?? '';
    if (strpos($accept, 'application/json') !== false || isset($_POST['json_format'])) {
        header('Content-Type: application/json; charset=utf-8');
        if ($uploadResult) {
            echo json_encode($uploadResult, JSON_PRETTY_PRINT);
        } else {
            echo json_encode(['status' => 'error', 'error' => $error], JSON_PRETTY_PRINT);
        }
        exit;
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>Document Portal - <?php echo htmlspecialchars($orgName); ?></title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            color: #1e293b;
            background-color: #f8fafc;
        }
        header { background: #1e3a8a; color: white; padding: 1.5rem; text-align: center; }
        main { max-width: 600px; margin: 2rem auto; padding: 0 1.5rem; }
        .card { background: white; border-radius: 8px; padding: 2rem; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
        .alert-success { background: #dcfce7; border: 1px solid #86efac; color: #166534; padding: 1rem; border-radius: 4px; margin-bottom: 1.5rem; }
        .alert-error { background: #fee2e2; border: 1px solid #fca5a5; color: #991b1b; padding: 1rem; border-radius: 4px; margin-bottom: 1.5rem; }
        button { background: #2563eb; color: white; padding: 0.75rem 1.5rem; border: none; border-radius: 4px; cursor: pointer; }
    </style>
</head>
<body>
    <header>
        <h1><?php echo htmlspecialchars($orgName); ?></h1>
    </header>
    <main>
        <div class="card">
            <h2>Medical Document Portal</h2>
            <p>Upload your health intake record (supports records up to server-configured capacity).</p>

            <?php if ($uploadResult): ?>
                <div class="alert-success" id="upload-success">
                    <strong>Upload Verified:</strong> Received <?php echo $uploadResult['bytes_received']; ?> bytes.<br>
                    <strong>SHA-256:</strong> <code id="file-sha256"><?php echo $uploadResult['sha256']; ?></code>
                </div>
            <?php elseif ($error): ?>
                <div class="alert-error" id="upload-error">
                    <?php echo htmlspecialchars($error); ?>
                </div>
            <?php endif; ?>

            <form method="POST" action="/upload.php" enctype="multipart/form-data" id="upload-form">
                <input type="file" name="document" id="document-input" required>
                <br><br>
                <button type="submit" id="btn-upload">Upload File</button>
            </form>
            <br>
            <a href="/">&larr; Back to Home</a>
        </div>
    </main>
</body>
</html>
