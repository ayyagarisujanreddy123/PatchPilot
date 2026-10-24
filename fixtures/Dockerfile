ARG BASE_IMAGE=php:8.3.35-apache
FROM ${BASE_IMAGE}

ARG CONFIG_PROFILE=pantry-default.ini

# Copy application files to document root
COPY site/ /var/www/html/

# Copy specified configuration profile to PHP conf.d
COPY profiles/${CONFIG_PROFILE} /usr/local/etc/php/conf.d/patchpilot-custom.ini

# Secure file permissions
RUN chown -R www-data:www-data /var/www/html \
    && chmod -R 755 /var/www/html

EXPOSE 80
