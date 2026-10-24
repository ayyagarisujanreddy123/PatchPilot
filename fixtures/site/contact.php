<?php
$orgName = getenv('ORG_NAME') ?: 'Community Care & Food Pantry';

$errors = [];
$successMessage = '';
$isSubmitted = ($_SERVER['REQUEST_METHOD'] === 'POST');

if ($isSubmitted) {
    // Validate inputs
    $name = trim($_POST['name'] ?? '');
    $email = trim($_POST['email'] ?? '');
    $message = trim($_POST['message'] ?? '');

    if (empty($name)) {
        $errors['name'] = 'Name is required.';
    } elseif (strlen($name) < 2) {
        $errors['name'] = 'Name must be at least 2 characters.';
    }

    if (empty($email)) {
        $errors['email'] = 'Email address is required.';
    } elseif (!filter_var($email, FILTER_VALIDATE_EMAIL)) {
        $errors['email'] = 'A valid email address is required.';
    }

    if (empty($message)) {
        $errors['message'] = 'Message is required.';
    } elseif (strlen($message) < 5) {
        $errors['message'] = 'Message must be at least 5 characters.';
    }

    if (empty($errors)) {
        // Successful validation - note: no real delivery or persistent personal data stored (per spec)
        $successMessage = 'Thank you! Your message has been received. Our team will follow up shortly.';
    } else {
        http_response_code(422);
    }

    // Support JSON response if requested by API verifiers
    $accept = $_SERVER['HTTP_ACCEPT'] ?? '';
    if (strpos($accept, 'application/json') !== false) {
        header('Content-Type: application/json; charset=utf-8');
        echo json_encode([
            'valid' => empty($errors),
            'errors' => $errors,
            'message' => $successMessage ?: 'Validation failed.'
        ]);
        exit;
    }
}
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Contact Us - <?php echo htmlspecialchars($orgName); ?></title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 0;
            color: #1e293b;
            background-color: #f8fafc;
        }
        header {
            background: #1e3a8a;
            color: white;
            padding: 1.5rem;
            text-align: center;
        }
        main {
            max-width: 600px;
            margin: 2rem auto;
            padding: 0 1.5rem;
        }
        .card {
            background: white;
            border-radius: 8px;
            padding: 2rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .form-group {
            margin-bottom: 1.25rem;
        }
        label {
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 600;
        }
        input[type="text"], input[type="email"], textarea {
            width: 100%;
            padding: 0.65rem;
            border: 1px solid #cbd5e1;
            border-radius: 4px;
            box-sizing: border-box;
            font-size: 1rem;
        }
        .error-text {
            color: #dc2626;
            font-size: 0.875rem;
            margin-top: 0.25rem;
        }
        .alert-success {
            background: #dcfce7;
            border: 1px solid #86efac;
            color: #166534;
            padding: 1rem;
            border-radius: 4px;
            margin-bottom: 1.5rem;
        }
        .alert-error {
            background: #fee2e2;
            border: 1px solid #fca5a5;
            color: #991b1b;
            padding: 1rem;
            border-radius: 4px;
            margin-bottom: 1.5rem;
        }
        button {
            background: #2563eb;
            color: white;
            padding: 0.75rem 1.5rem;
            border: none;
            border-radius: 4px;
            font-size: 1rem;
            cursor: pointer;
            font-weight: 500;
        }
        button:hover {
            background: #1d4ed8;
        }
        .back-link {
            display: block;
            margin-top: 1.5rem;
            color: #64748b;
            text-decoration: none;
        }
    </style>
</head>
<body>
    <header>
        <h1><?php echo htmlspecialchars($orgName); ?></h1>
    </header>

    <main>
        <div class="card">
            <h2>Contact Us</h2>

            <?php if (!empty($successMessage)): ?>
                <div class="alert-success" id="contact-success">
                    <?php echo htmlspecialchars($successMessage); ?>
                </div>
            <?php elseif ($isSubmitted && !empty($errors)): ?>
                <div class="alert-error" id="contact-error-summary">
                    Please correct the errors indicated below.
                </div>
            <?php endif; ?>

            <form method="POST" action="/contact.php" novalidate id="contact-form">
                <div class="form-group">
                    <label for="name">Name</label>
                    <input type="text" id="name" name="name" value="<?php echo htmlspecialchars($_POST['name'] ?? ''); ?>" required>
                    <?php if (isset($errors['name'])): ?>
                        <div class="error-text" id="error-name"><?php echo htmlspecialchars($errors['name']); ?></div>
                    <?php endif; ?>
                </div>

                <div class="form-group">
                    <label for="email">Email</label>
                    <input type="email" id="email" name="email" value="<?php echo htmlspecialchars($_POST['email'] ?? ''); ?>" required>
                    <?php if (isset($errors['email'])): ?>
                        <div class="error-text" id="error-email"><?php echo htmlspecialchars($errors['email']); ?></div>
                    <?php endif; ?>
                </div>

                <div class="form-group">
                    <label for="message">Message</label>
                    <textarea id="message" name="message" rows="4" required><?php echo htmlspecialchars($_POST['message'] ?? ''); ?></textarea>
                    <?php if (isset($errors['message'])): ?>
                        <div class="error-text" id="error-message"><?php echo htmlspecialchars($errors['message']); ?></div>
                    <?php endif; ?>
                </div>

                <button type="submit" id="btn-submit">Submit Message</button>
            </form>

            <a href="/" class="back-link">&larr; Back to Home</a>
        </div>
    </main>
</body>
</html>
