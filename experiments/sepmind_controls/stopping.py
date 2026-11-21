"""Submission trigger based on simulator convergence and frozen product targets."""

import math


def product_targets_met(record, target):
    """Screen the raw product values, without performing an independent review."""
    checks = record.get('checks', {})
    if (record.get('status') != 'ok' or checks.get('flowsheet_solved') is not True
            or checks.get('product_compositions_imposed') is not False):
        return False

    try:
        outputs = record['outputs']
        top = outputs['distillate']
        x_top = top['mole_fractions'][0]
        if not math.isfinite(x_top) or not target.distillate_mole_fraction <= x_top <= 1:
            return False
        if target.bottoms_mole_fraction is not None:
            x_bottom = outputs['bottoms']['mole_fractions'][0]
            if not math.isfinite(x_bottom) or not 0 <= x_bottom <= target.bottoms_mole_fraction:
                return False
        if target.key_component_recovery is not None:
            feed = outputs['feed']
            feed_light = feed['flow_mol_s'] * feed['mole_fractions'][0]
            if not math.isfinite(feed_light) or feed_light <= 0:
                return False
            recovery = top['flow_mol_s'] * x_top / feed_light
            if not math.isfinite(recovery) or recovery < target.key_component_recovery:
                return False
        return True
    except (KeyError, IndexError, TypeError, ZeroDivisionError, OverflowError):
        return False
