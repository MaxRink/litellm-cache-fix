use litellm_auth_aws::AwsParams;
use serde::Deserialize;

/// The typed subset of Python's `GenericLiteLLMParams` that provider configs read.
///
/// One flattened group per credential family, so a host projects exactly [`Self::fields`]
/// out of a caller's kwargs and a config reaches for `litellm_params.aws`, never a map.
#[derive(Clone, Debug, Default, PartialEq, Eq, Deserialize)]
pub struct LitellmParams {
    #[serde(flatten)]
    pub aws: AwsParams,
}

impl LitellmParams {
    /// The wire names a host projects into this type; everything else in the kwargs is not
    /// a litellm param the configs read.
    pub fn fields() -> impl Iterator<Item = &'static str> {
        AwsParams::FIELDS.into_iter()
    }
}

#[cfg(test)]
mod tests {
    use rstest::rstest;
    use serde_json::{Value, json};

    use super::*;

    #[rstest]
    #[case::aws_group(
        json!({"aws_region_name": "eu-west-1", "aws_access_key_id": "AKIA"}),
        LitellmParams {
            aws: AwsParams {
                aws_region_name: Some("eu-west-1".into()),
                aws_access_key_id: Some("AKIA".into()),
                ..AwsParams::default()
            },
        },
    )]
    #[case::explicit_null_is_absent(
        json!({"aws_region_name": null}),
        LitellmParams::default(),
    )]
    #[case::keys_outside_the_groups_are_ignored(
        json!({"messages": [], "max_tokens": 5, "vertex_project": "p"}),
        LitellmParams::default(),
    )]
    fn deserializes_the_credential_groups_from_caller_kwargs(
        #[case] kwargs: Value,
        #[case] expected: LitellmParams,
    ) {
        assert_eq!(
            serde_json::from_value::<LitellmParams>(kwargs).unwrap(),
            expected
        );
    }

    #[test]
    fn a_non_string_param_is_rejected() {
        assert!(serde_json::from_value::<LitellmParams>(json!({"aws_region_name": 7})).is_err());
    }

    #[test]
    fn fields_fill_every_group() {
        let filled: Value = LitellmParams::fields()
            .map(|name| (name.to_string(), Value::from(name)))
            .collect::<serde_json::Map<_, _>>()
            .into();
        let typed: LitellmParams = serde_json::from_value(filled).unwrap();
        assert_eq!(
            serde_json::to_value(&typed.aws)
                .unwrap()
                .as_object()
                .unwrap()
                .values()
                .filter(|value| value.is_null())
                .count(),
            0
        );
    }
}
