<?php
$orgName = getenv('ORG_NAME') ?: 'Community Care & Food Pantry';
$tagline = getenv('ORG_TAGLINE') ?: 'Serving our neighbors with fresh food, dignity, and compassion.';
$capabilities = getenv('CAPABILITIES') ? explode(',', getenv('CAPABILITIES')) : ['homepage', 'contact'];
$hasUpload = in_array('upload', $capabilities);
?>
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title><?php echo htmlspecialchars($orgName); ?> - Home</title>
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
            background: linear-gradient(135deg, #1e3a8a, #3b82f6);
            color: white;
            padding: 3rem 1.5rem;
            text-align: center;
        }
        header h1 {
            margin: 0 0 0.5rem 0;
            font-size: 2.25rem;
        }
        header p {
            margin: 0;
            font-size: 1.15rem;
            opacity: 0.95;
        }
        main {
            max-width: 800px;
            margin: 2rem auto;
            padding: 0 1.5rem;
        }
        .card {
            background: white;
            border-radius: 8px;
            padding: 2rem;
            margin-bottom: 2rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        .nav-links a {
            display: inline-block;
            margin-right: 1.25rem;
            color: #2563eb;
            text-decoration: none;
            font-weight: 500;
        }
        .nav-links a:hover {
            text-decoration: underline;
        }
        footer {
            text-align: center;
            padding: 2rem;
            color: #64748b;
            font-size: 0.875rem;
        }
    </style>
</head>
<body>
    <header>
        <h1 id="org-title"><?php echo htmlspecialchars($orgName); ?></h1>
        <p id="org-tagline"><?php echo htmlspecialchars($tagline); ?></p>
    </header>

    <main>
        <section class="card">
            <h2>Welcome</h2>
            <p>We are a local community organization dedicated to supporting families, health, and well-being.</p>
            <div class="nav-links">
                <a href="/contact.php" id="link-contact">Contact Us</a>
                <?php if ($hasUpload): ?>
                    <a href="/upload.php" id="link-upload">Document Portal</a>
                <?php endif; ?>
                <a href="/runtime.php" id="link-runtime">Serving Status</a>
            </div>
        </section>
    </main>

    <footer>
        <p>&copy; <?php echo date('Y'); ?> <?php echo htmlspecialchars($orgName); ?>. Operating on PatchPilot Managed Infrastructure.</p>
    </footer>
</body>
</html>
