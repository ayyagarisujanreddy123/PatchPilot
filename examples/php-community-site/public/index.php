<?php
header('Content-Type: text/html; charset=utf-8');
?>
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Community Care · PHP repair demo</title>
<style>
body{margin:0;background:#f6f7f2;color:#17313a;font:16px/1.6 system-ui,sans-serif}main{max-width:760px;margin:10vh auto;padding:2rem}small{color:#087f73;font-weight:650;letter-spacing:.1em}h1{font-size:clamp(2rem,6vw,3.5rem);line-height:1.1}p{max-width:60ch}nav{display:flex;gap:1rem;flex-wrap:wrap;margin:2rem 0}a{color:#087f73;border:1px solid #b7cfc5;border-radius:9px;padding:.8rem 1rem;text-decoration:none}a:focus-visible{outline:3px solid #235ee8;outline-offset:4px}.note{font-size:.85rem;color:#526973;border-top:1px solid #d5e0d9;padding-top:1rem}
</style></head>
<body><main><small>COMMUNITY CARE · OWNED DEMO</small><h1>A little help.<br>A stronger community.</h1>
<p>This working PHP site demonstrates a repository-connected security repair. Its contact form validates submissions without sending email. Uploads are hashed and immediately discarded.</p>
<nav aria-label="Website functions"><a href="/contact.php">Contact our team</a><a href="/upload.php">Upload an application document</a></nav>
<p class="note">This demo intentionally starts with verbose PHP settings. PatchPilot prepares a hardened configuration and checks that these functions still work in an isolated copy. Use test data only.</p>
</main></body></html>
