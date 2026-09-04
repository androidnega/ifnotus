<?php

/**
 * IFNOTUS Roundcube branding — clean login CSS + logo overrides.
 */
class ifnotus_brand extends rcube_plugin
{
    public $task = '.*';

    public function init()
    {
        $this->include_stylesheet($this->local_skin_path() . '/ifnotus.css');
    }
}
